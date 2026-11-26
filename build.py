#!/usr/bin/env python3
"""오늘 뭐 입지 — 뉴스·증시 데이터 만들기 (무료 공개 데이터만 사용)

GitHub Actions가 15분마다 실행해서 out/ 폴더에 news.json, market.json 을 만들어요.
- 증시: 네이버 증권(국내·해외 지수, 환율, 금리, 원자재, 순위), Nasdaq(미국 종목), CoinGecko·Upbit(코인),
        alternative.me(코인 공포탐욕), ForexFactory(경제 일정), Nasdaq(실적 발표)
- 뉴스: Bloomberg·CNBC·FT·WSJ·MarketWatch·CoinDesk·Fed·Economist RSS, Google 뉴스(Reuters 등 주제 검색),
        연합뉴스·매일경제 RSS
- 요약·번역: (선택) 무료 Gemini API 키가 있으면 AI 요약 → 없으면 무료 번역 + 규칙 기반 요약
표준 라이브러리만 사용해요 (설치 필요 없음).
"""
import concurrent.futures as cf
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
os.makedirs(OUT, exist_ok=True)
KST = timezone(timedelta(hours=9))
NOW = datetime.now(timezone.utc)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
LOG = []


def log(*a):
    msg = ' '.join(str(x) for x in a)
    LOG.append(msg)
    print(msg, flush=True)


def get(url, headers=None, timeout=20, data=None, tries=2):
    h = {'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', errors='replace')
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def jget(url, **kw):
    return json.loads(get(url, headers={'Accept': 'application/json, text/plain, */*', **kw.pop('headers', {})}, **kw))


def num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(',', '').replace('$', '').replace('%', '').strip()
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()+')
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def pmap(fn, items, workers=8):
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def safe(fn, default=None, label=''):
    try:
        return fn()
    except Exception as e:  # noqa
        log('!!', label or getattr(fn, '__name__', 'task'), type(e).__name__, str(e)[:160])
        return default


def load_prev(name):
    try:
        with open(os.path.join(OUT, name), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


CACHE = load_prev('cache.json') or {}
CACHE.setdefault('tr', {})   # 번역 캐시 {hash: 한국어 제목}
CACHE.setdefault('ai', {})   # AI 요약 캐시


# ======================================================================
#  증시
# ======================================================================
NV = 'https://m.stock.naver.com/api'
NVW = 'https://api.stock.naver.com'
NVF = 'https://m.stock.naver.com/front-api'

WORLD = [  # (코드, 이름, 지역)
    ('.INX', 'S&P 500', '미국'), ('.IXIC', '나스닥', '미국'), ('.DJI', '다우존스', '미국'), ('.SOX', '필라델피아 반도체', '미국'),
    ('.VIX', 'VIX 변동성', '미국'),
    ('.N225', '닛케이 225', '아시아'), ('.SSEC', '상해종합', '아시아'), ('.HSI', '항셍', '아시아'), ('.TWII', '대만 가권', '아시아'),
    ('.GDAXI', '독일 DAX', '유럽'), ('.FTSE', '영국 FTSE 100', '유럽'), ('.STOXX50E', '유로스톡스 50', '유럽'),
]


def closes_from(rows):
    out = []
    for r in reversed(rows or []):
        v = num(r.get('closePrice'))
        if v is not None:
            out.append(round(v, 4))
    return out


def kr_index(code):
    b = jget(f'{NV}/index/{code}/basic')
    hist = safe(lambda: jget(f'{NV}/index/{code}/price?page=1&pageSize=30'), [], f'hist {code}')
    return {'id': code, 'name': b.get('stockName'), 'price': num(b.get('closePrice')), 'chg': num(b.get('compareToPreviousClosePrice')),
            'pct': num(b.get('fluctuationsRatio')), 'status': b.get('marketStatus'), 'at': b.get('localTradedAt'),
            'spark': closes_from(hist), 'url': b.get('endUrl')}


def world_index(t):
    code, name, region = t
    b = jget(f'{NVW}/index/{code}/basic')
    hist = safe(lambda: jget(f'{NVW}/index/{code}/price?page=1&pageSize=30'), [], f'hist {code}')
    return {'id': code, 'name': name, 'region': region, 'price': num(b.get('closePrice')), 'chg': num(b.get('compareToPreviousClosePrice')),
            'pct': num(b.get('fluctuationsRatio')), 'status': b.get('marketStatus'), 'at': b.get('localTradedAt'),
            'spark': closes_from(hist), 'url': b.get('endUrl')}


def majors():
    d = jget(f'{NVF}/marketIndex/majors')['result']
    pick = lambda it: {'id': it.get('reutersCode'), 'name': it.get('name'), 'price': num(it.get('closePrice')),
                       'chg': num(it.get('fluctuations')), 'pct': num(it.get('fluctuationsRatio')),
                       'delay': it.get('delayTimeName'), 'at': it.get('localTradedAt')}
    out = {k: [pick(x) for x in v] for k, v in d.items() if isinstance(v, list)}
    return out


def investor(code):
    d = jget(f'{NV}/index/{code}/trend')
    return {'date': d.get('bizdate'), 'personal': num(d.get('personalValue')), 'foreign': num(d.get('foreignValue')),
            'inst': num(d.get('institutionalValue'))}


# 국내 대형주 업종 (마켓맵 묶음용)
KR_SECTOR = {}
for sec, codes in {
    '반도체': '005930 005935 000660 042700 036930 222800 058470 039030 240810 403870 031980 095340 319660 030530 009150',
    '2차전지': '373220 006400 247540 086520 003670 051910',
    '바이오': '207940 068270 196170 000250 028300 214450 310210 145020 141080 226950 298380 087010 140410 0126Z0 326030 128940',
    '자동차': '005380 000270 012330 086280 307950',
    '금융': '105560 055550 086790 316140 138040 024110 006800 032830 000810 005830 323410 071050 039490',
    '조선·방산': '012450 329180 009540 042660 010140 047810 272210 079550 064350',
    '전력·에너지': '034020 010120 267260 298040 015760 096770 010950 437730',
    '인터넷·게임': '035420 035720 018260 259960 251270 036570 293490',
    '로봇': '277810 108490 058610',
    '지주': '402340 028260 034730 003550 267250 180640 000150 001040',
    '소재·철강': '005490 010130 011170',
    '통신': '017670 030200 032640 010170',
    '소비재': '033780 278470 003230 257720 041510 090430 097950 271560',
    '운송': '011200 003490',
    '전자·가전': '066570 011070',
    '건설': '028050 000720',
}.items():
    for c in codes.split():
        KR_SECTOR[c] = sec


def kr_stock(s, market):
    return {'code': s['itemCode'], 'name': s['stockName'], 'mkt': market, 'type': s.get('stockEndType'),
            'price': num(s.get('closePrice')), 'chg': num(s.get('compareToPreviousClosePrice')), 'pct': num(s.get('fluctuationsRatio')),
            'val': num(s.get('accumulatedTradingValue')),   # 거래대금 (백만원)
            'cap': num(s.get('marketValue')),               # 시가총액 (억원)
            'sector': KR_SECTOR.get(s['itemCode'], '기타')}


def kr_list(kind, market, size=100):
    d = jget(f'{NV}/stocks/{kind}/{market}?page=1&pageSize={size}')
    return [kr_stock(s, market) for s in d.get('stocks', [])]


def kr_market():
    jobs = {(k, m): (k, m) for k in ('marketValue', 'priceTop', 'up', 'down') for m in ('KOSPI', 'KOSDAQ')}
    res = dict(zip(jobs, pmap(lambda km: safe(lambda: kr_list(km[0], km[1]), [], f'kr {km}'), list(jobs), 8)))
    stocks = lambda L: [x for x in L if x['type'] == 'stock']
    # 마켓맵: 코스피 시총 상위 50 + 코스닥 상위 20
    mp = stocks(res[('marketValue', 'KOSPI')])[:50] + stocks(res[('marketValue', 'KOSDAQ')])[:20]
    # 거래대금 TOP10 (주식만)
    val = sorted(stocks(res[('priceTop', 'KOSPI')] + res[('priceTop', 'KOSDAQ')]), key=lambda x: -(x['val'] or 0))[:10]
    # 상승·하락 TOP10: 거래대금 100억 이상 '인기' 종목 중에서 (부족하면 30억 이상)
    pool = {x['code']: x for x in stocks(sum(res.values(), [])) if x['pct'] is not None}

    def rank(sign):
        for th in (10000, 3000, 0):
            L = sorted([x for x in pool.values() if (x['val'] or 0) >= th and x['pct'] * sign > 0], key=lambda x: -x['pct'] * sign)
            if len(L) >= 10 or th == 0:
                return L[:10]
    return {'map': mp, 'top': {'value': val, 'up': rank(1), 'down': rank(-1)}}


US_SECTOR = {'Technology': '기술', 'Telecommunications': '통신', 'Health Care': '헬스케어', 'Finance': '금융',
             'Consumer Discretionary': '경기소비재', 'Consumer Staples': '필수소비재', 'Industrials': '산업재', 'Energy': '에너지',
             'Utilities': '유틸리티', 'Real Estate': '부동산', 'Basic Materials': '소재', 'Miscellaneous': '기타'}
US_KO = dict(x.split(':') for x in '''AAPL:애플 MSFT:마이크로소프트 NVDA:엔비디아 GOOGL:알파벳A GOOG:알파벳C AMZN:아마존 META:메타 TSLA:테슬라 AVGO:브로드컴
LLY:일라이릴리 JPM:JP모건 V:비자 UNH:유나이티드헬스 XOM:엑슨모빌 MA:마스터카드 JNJ:존슨앤드존슨 PG:P&G HD:홈디포 COST:코스트코 ORCL:오라클
ABBV:애브비 MRK:머크 CVX:셰브론 KO:코카콜라 PEP:펩시코 AMD:AMD NFLX:넷플릭스 ADBE:어도비 CRM:세일즈포스 BAC:뱅크오브아메리카 WMT:월마트
TMO:써모피셔 MCD:맥도날드 CSCO:시스코 ACN:액센츄어 ABT:애보트 LIN:린데 DIS:디즈니 INTC:인텔 QCOM:퀄컴 TXN:텍사스인스트루먼트 IBM:IBM
AMAT:어플라이드머티리얼즈 MU:마이크론 PLTR:팔란티어 GS:골드만삭스 MS:모건스탠리 WFC:웰스파고 C:씨티그룹 BLK:블랙록 UBER:우버 PYPL:페이팔
SHOP:쇼피파이 ARM:ARM TSM:TSMC ASML:ASML BABA:알리바바 PDD:PDD NVO:노보노디스크 SAP:SAP TM:도요타 AZN:아스트라제네카 SONY:소니
COIN:코인베이스 MSTR:스트래티지 HOOD:로빈후드 SMCI:슈퍼마이크로 DELL:델 MRVL:마벨 LRCX:램리서치 KLAC:KLA SNOW:스노우플레이크
PANW:팔로알토 CRWD:크라우드스트라이크 NOW:서비스나우 INTU:인튜이트 ISRG:인튜이티브서지컬 AMGN:암젠 GILD:길리어드 PFE:화이자 BA:보잉
CAT:캐터필러 GE:GE에어로스페이스 RTX:RTX LMT:록히드마틴 HON:하니웰 UPS:UPS NKE:나이키 SBUX:스타벅스 T:AT&T VZ:버라이즌 TMUS:T모바일
CMCSA:컴캐스트 SPGI:S&P글로벌 AXP:아메리칸익스프레스 SCHW:찰스슈왑 NEE:넥스트에라 LOW:로우스 BKNG:부킹홀딩스 ABNB:에어비앤비 RIVN:리비안
LCID:루시드 F:포드 GM:GM SOFI:소파이 IONQ:아이온큐 RGTI:리게티 APP:앱러빈 VRT:버티브 ANET:아리스타 CEG:컨스텔레이션에너지 OKLO:오클로
SMR:뉴스케일 NBIS:네비우스 CRWV:코어위브 RDDT:레딧 BRK/B:버크셔B BRK/A:버크셔A DE:디어 MDT:메드트로닉 VRTX:버텍스 REGN:리제네론
NVDL:NVDL TSLL:TSLL SOXL:SOXL TQQQ:TQQQ QQQ:QQQ SPY:SPY HIMS:힘스앤허스 CVNA:카바나 ASTS:AST스페이스모바일 RKLB:로켓랩 DUOL:듀오링고
SNDK:샌디스크 WDC:웨스턴디지털 STX:씨게이트 TER:테라다인 ON:온세미 MCHP:마이크로칩 ADI:아나로그디바이스 NXPI:NXP CDNS:케이던스 SNPS:시놉시스
APH:암페놀 ETN:이튼 GEV:GE버노바 VST:비스트라 TLN:탈렌 ORLY:오라일리 TJX:TJX MELI:메르카도리브레 SPOT:스포티파이 NET:클라우드플레어
DDOG:데이터독 ZS:지스케일러 MDB:몽고DB TTD:트레이드데스크 WDAY:워크데이 TEAM:아틀라시안 ADSK:오토데스크 FTNT:포티넷 CHTR:차터
BX:블랙스톤 KKR:KKR APO:아폴로 CME:CME ICE:ICE COF:캐피털원 PGR:프로그레시브 CB:처브 MMC:마시앤맥레넌 ELV:엘레번스 CI:시그나
SPCX:스페이스X ANT:앤트로픽 CVS:CVS헬스 BMY:BMS ZTS:조에티스 SYK:스트라이커 BSX:보스턴사이언티픽 DHR:다나허 MO:알트리아 PM:필립모리스 MDLZ:몬델리즈 CL:콜게이트
'''.split())


def us_short(name):
    name = re.sub(r'\s+(Common Stock|Class [A-C]\b.*|Ordinary Shares|American Depos\w* Shares.*|ADS\b.*|Inc\.?|Incorporated|Corporation|Corp\.?|Holdings?|Limited|Ltd\.?|plc|N\.V\.|S\.A\.|PBC)\b.*$', '', name or '', flags=re.I)
    name = name.strip(' ,.')
    if name.isupper() and len(name) > 4:
        name = name.title()
    return name[:22]


def us_market():
    d = jget('https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=0&offset=0&download=true',
             headers={'Origin': 'https://www.nasdaq.com', 'Referer': 'https://www.nasdaq.com/'}, timeout=40)
    rows = d['data']['rows']
    L = []
    for r in rows:
        cap, price, pct, vol = num(r.get('marketCap')), num(r.get('lastsale')), num(r.get('pctchange')), num(r.get('volume'))
        if not cap or price is None or pct is None:
            continue
        sym = r['symbol'].strip()
        L.append({'sym': sym, 'name': US_KO.get(sym) or us_short(r.get('name')), 'en': us_short(r.get('name')), 'price': price, 'pct': round(pct, 2),
                  'cap': cap, 'val': round((vol or 0) * price), 'sector': US_SECTOR.get(r.get('sector') or '', '기타'),
                  'country': r.get('country') or ''})
    big = sorted(L, key=lambda x: -x['cap'])
    us_only = [x for x in big if x['country'] == 'United States' and '/' not in x['sym'] or x['sym'] in ('BRK/B',)]
    mp = [x for x in us_only if x['sym'] not in ('GOOG', 'BRK/A')][:100]
    liquid = [x for x in L if x['cap'] >= 5e9]
    top = {'value': sorted([x for x in L if x['cap'] >= 1e9], key=lambda x: -x['val'])[:10],
           'up': sorted([x for x in liquid if x['pct'] > 0], key=lambda x: -x['pct'])[:10],
           'down': sorted([x for x in liquid if x['pct'] < 0], key=lambda x: x['pct'])[:10]}
    for x in mp + sum(top.values(), []):
        x.pop('country', None)
    return {'map': mp, 'top': top}


def crypto():
    ids = 'bitcoin,ethereum,ripple,solana,binancecoin,dogecoin,cardano,tron'
    coins = jget(f'https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}&order=market_cap_desc&price_change_percentage=24h')
    out = [{'id': c['id'], 'sym': c['symbol'].upper(), 'name': c['name'], 'price': c['current_price'], 'pct': round(c.get('price_change_percentage_24h') or 0, 2),
            'cap': c.get('market_cap')} for c in coins if c['symbol'].lower() not in ('usdt', 'usdc', 'steth', 'wsteth', 'wbtc', 'weth', 'usds', 'usde')][:8]
    up = safe(lambda: jget('https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE,KRW-ADA,KRW-TRX'), [], 'upbit')
    upk = {x['market'].split('-')[1]: x for x in up}
    for c in out:
        u = upk.get(c['sym'])
        if u:
            c['krw'] = u['trade_price']
            c['krwPct'] = round(u['signed_change_rate'] * 100, 2)
    fg = safe(lambda: jget('https://api.alternative.me/fng/?limit=1')['data'][0], None, 'crypto fng')
    return {'coins': out, 'fg': {'value': int(fg['value']), 'label': fg['value_classification']} if fg else None}


FF_KO = [  # (영문 일부, 한국어)
    ('Federal Funds Rate', '미국 기준금리 결정'), ('FOMC Meeting Minutes', 'FOMC 의사록'), ('FOMC Statement', 'FOMC 성명'), ('FOMC Press Conference', 'FOMC 기자회견'),
    ('Fed Chair', '연준 의장 발언'), ('Core CPI m/m', '근원 소비자물가(전월비)'), ('CPI m/m', '소비자물가(전월비)'), ('CPI y/y', '소비자물가(전년비)'),
    ('Core PCE Price Index m/m', '근원 PCE 물가(전월비)'), ('PCE Price Index', 'PCE 물가'), ('Core PPI m/m', '근원 생산자물가'), ('PPI m/m', '생산자물가(전월비)'),
    ('Non-Farm Employment Change', '비농업 고용'), ('Unemployment Rate', '실업률'), ('Average Hourly Earnings', '평균 시간당 임금'),
    ('Unemployment Claims', '신규 실업수당 청구'), ('ADP Non-Farm', 'ADP 민간고용'), ('JOLTS Job Openings', 'JOLTS 구인'),
    ('Advance GDP q/q', 'GDP 속보치'), ('Prelim GDP q/q', 'GDP 잠정치'), ('Final GDP q/q', 'GDP 확정치'), ('GDP', 'GDP'),
    ('Core Retail Sales m/m', '근원 소매판매'), ('Retail Sales m/m', '소매판매'), ('ISM Manufacturing PMI', 'ISM 제조업 PMI'),
    ('ISM Services PMI', 'ISM 서비스업 PMI'), ('Flash Manufacturing PMI', '제조업 PMI 예비치'), ('Flash Services PMI', '서비스업 PMI 예비치'),
    ('CB Consumer Confidence', '컨퍼런스보드 소비자신뢰'), ('Prelim UoM Consumer Sentiment', '미시간대 소비자심리 예비치'),
    ('UoM Consumer Sentiment', '미시간대 소비자심리'), ('Durable Goods Orders', '내구재 주문'), ('Pending Home Sales', '잠정 주택판매'),
    ('Existing Home Sales', '기존 주택판매'), ('New Home Sales', '신규 주택판매'), ('Building Permits', '건축허가'), ('Housing Starts', '주택착공'),
    ('Crude Oil Inventories', 'EIA 원유재고'), ('Natural Gas Storage', '천연가스 재고'), ('Trade Balance', '무역수지'),
    ('Empire State Manufacturing', '뉴욕 제조업지수'), ('Philly Fed Manufacturing', '필라델피아 제조업지수'), ('Industrial Production', '산업생산'),
    ('Main Refinancing Rate', 'ECB 기준금리'), ('Monetary Policy Statement', '통화정책 성명'), ('BOJ Policy Rate', '일본은행 기준금리'),
    ('Caixin Manufacturing PMI', '차이신 제조업 PMI'), ('Manufacturing PMI', '제조업 PMI'), ('Bank Holiday', '휴장'), ('Speaks', '발언'),
]
FF_CC = {'USD': '🇺🇸', 'EUR': '🇪🇺', 'JPY': '🇯🇵', 'CNY': '🇨🇳', 'GBP': '🇬🇧'}


def calendar():
    rows = jget('https://nfs.faireconomy.media/ff_calendar_thisweek.json')
    out = []
    for r in rows:
        cc, imp = r.get('country'), r.get('impact')
        if not ((cc == 'USD' and imp in ('High', 'Medium')) or (cc in ('EUR', 'JPY', 'CNY') and imp == 'High')):
            continue
        try:
            t = datetime.fromisoformat(r['date']).astimezone(KST)
        except Exception:
            continue
        title = r.get('title', '')
        ko = next((k for e, k in FF_KO if e.lower() in title.lower()), None)
        out.append({'t': t.isoformat(), 'cc': cc, 'flag': FF_CC.get(cc, ''), 'imp': imp, 'en': title, 'ko': ko,
                    'f': r.get('forecast') or '', 'p': r.get('previous') or '', 'a': r.get('actual') or ''})
    return out


def earnings():
    out = []
    for dd in (0, 1):
        day = (NOW.astimezone(timezone(timedelta(hours=-5))) + timedelta(days=dd)).date().isoformat()
        d = safe(lambda: jget(f'https://api.nasdaq.com/api/calendar/earnings?date={day}',
                              headers={'Origin': 'https://www.nasdaq.com', 'Referer': 'https://www.nasdaq.com/'}), None, 'earnings')
        rows = ((d or {}).get('data') or {}).get('rows') or []
        for r in rows:
            cap = num(r.get('marketCap'))
            if cap and cap >= 3e10:
                sym = r.get('symbol')
                out.append({'date': day, 'sym': sym, 'name': US_KO.get(sym) or us_short(r.get('name')), 'cap': cap,
                            'time': {'time-pre-market': '장 전', 'time-after-hours': '장 마감 후'}.get(r.get('time'), ''),
                            'eps': r.get('eps') or '', 'est': r.get('epsForecast') or '', 'surprise': r.get('surprise') or ''})
    return sorted(out, key=lambda x: (x['date'], -x['cap']))[:16]


def build_market():
    t0 = time.time()
    jobs = {
        'kospi': lambda: kr_index('KOSPI'), 'kosdaq': lambda: kr_index('KOSDAQ'),
        'world': lambda: [w for w in pmap(lambda t: safe(lambda: world_index(t), None, f'world {t[0]}'), WORLD, 6) if w],
        'majors': majors, 'invK': lambda: investor('KOSPI'), 'invQ': lambda: investor('KOSDAQ'),
        'kr': kr_market, 'us': us_market, 'crypto': crypto, 'cal': calendar, 'earn': earnings,
    }
    with cf.ThreadPoolExecutor(6) as ex:
        fut = {k: ex.submit(safe, f, None, k) for k, f in jobs.items()}
        R = {k: f.result() for k, f in fut.items()}
    m = {'updated': NOW.astimezone(KST).isoformat(timespec='minutes'),
         'kr': {'indices': [x for x in (R['kospi'], R['kosdaq']) if x], 'investor': {'KOSPI': R['invK'], 'KOSDAQ': R['invQ']},
                **(R['kr'] or {'map': [], 'top': {}})},
         'world': R['world'] or [], 'macro': R['majors'] or {}, 'us': R['us'] or {'map': [], 'top': {}},
         'crypto': R['crypto'] or {}, 'calendar': R['cal'] or [], 'earnings': R['earn'] or []}
    log(f'market built in {time.time() - t0:.1f}s')
    return m


# ======================================================================
#  뉴스
# ======================================================================
def gnews(q, lang='en'):
    if lang == 'ko':
        return f'https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=ko&gl=KR&ceid=KR:ko'
    return f'https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en'


# (주소, 매체 이름(없으면 기사에서), 언어, 분류, 신뢰 가중치)
FEEDS = [
    ('https://feeds.bloomberg.com/markets/news.rss', 'Bloomberg', 'en', 'markets', 1.0),
    ('https://feeds.bloomberg.com/economics/news.rss', 'Bloomberg', 'en', 'economy', 1.0),
    ('https://www.cnbc.com/id/100003114/device/rss/rss.html', 'CNBC', 'en', 'markets', 0.85),
    ('https://www.cnbc.com/id/15839135/device/rss/rss.html', 'CNBC', 'en', 'markets', 0.85),
    ('https://www.cnbc.com/id/20910258/device/rss/rss.html', 'CNBC', 'en', 'economy', 0.85),
    ('https://www.ft.com/markets?format=rss', 'Financial Times', 'en', 'markets', 1.0),
    ('https://feeds.a.dj.com/rss/RSSMarketsMain.xml', 'WSJ', 'en', 'markets', 1.0),
    ('https://feeds.content.dowjones.io/public/rss/mw_topstories', 'MarketWatch', 'en', 'markets', 0.8),
    ('https://www.coindesk.com/arc/outboundfeeds/rss/', 'CoinDesk', 'en', 'crypto', 0.8),
    ('https://www.federalreserve.gov/feeds/press_all.xml', 'Federal Reserve', 'en', 'economy', 1.0),
    ('https://www.economist.com/finance-and-economics/rss.xml', 'The Economist', 'en', 'economy', 0.9),
    (gnews('site:reuters.com (markets OR stocks OR economy) when:1d'), None, 'en', 'markets', 1.0),
    (gnews('(Treasury yields OR "bond market" OR "10-year yield") when:1d'), None, 'en', 'bonds', 0.9),
    (gnews('("Federal Reserve" OR inflation OR CPI OR "rate cut") when:1d'), None, 'en', 'economy', 0.9),
    (gnews('("oil prices" OR OPEC OR "gold prices") when:1d'), None, 'en', 'commodities', 0.85),
    (gnews('(bitcoin OR ethereum OR crypto) when:1d'), None, 'en', 'crypto', 0.8),
    (gnews('(Nvidia OR Apple OR Microsoft OR Tesla OR Alphabet OR Amazon OR Meta) stock when:1d'), None, 'en', 'tech', 0.85),
    (gnews('"Goldman Sachs" when:2d'), None, 'en', 'people', 0.9),
    (gnews('"Michael Burry" when:7d'), None, 'en', 'people', 0.9),
    (gnews('("Berkshire Hathaway" OR "Warren Buffett") when:3d'), None, 'en', 'people', 0.9),
    (gnews('(JPMorgan OR "Jamie Dimon" OR BlackRock OR "Larry Fink" OR "Morgan Stanley") when:2d'), None, 'en', 'people', 0.9),
    (gnews('("Bill Ackman" OR "Ray Dalio" OR "Cathie Wood" OR "Stanley Druckenmiller") when:5d'), None, 'en', 'people', 0.85),
    ('https://www.yna.co.kr/rss/economy.xml', '연합뉴스', 'ko', 'korea', 0.85),
    ('https://www.yna.co.kr/rss/international.xml', '연합뉴스', 'ko', 'world', 0.8),
    ('https://www.mk.co.kr/rss/50200011/', '매일경제', 'ko', 'korea', 0.8),
    (gnews('(미국 증시 OR 뉴욕증시 OR 나스닥) when:1d', 'ko'), None, 'ko', 'markets', 0.8),
    (gnews('(국채 금리 OR 채권 시장 OR 국고채) when:1d', 'ko'), None, 'ko', 'bonds', 0.8),
    (gnews('(비트코인 OR 가상자산 OR 이더리움) when:1d', 'ko'), None, 'ko', 'crypto', 0.75),
    (gnews('(골드만삭스 OR 마이클 버리 OR 버크셔 OR JP모건 OR 블랙록) when:3d', 'ko'), None, 'ko', 'people', 0.8),
    (gnews('(연준 OR 파월 OR 금리 인하 OR 한국은행 기준금리) when:2d', 'ko'), None, 'ko', 'economy', 0.85),
    (gnews('(코스피 OR 코스닥 OR 원달러 환율 OR 외국인 순매수) when:1d', 'ko'), None, 'ko', 'korea', 0.85),
]
CAT_KO = {'markets': '증시', 'economy': '경제·정책', 'bonds': '채권·금리', 'commodities': '원자재', 'crypto': '코인', 'tech': '빅테크·AI',
          'people': '인물·기관', 'korea': '국내', 'world': '국제'}
AUTH = {'Reuters': 1.0, 'Bloomberg': 1.0, 'Financial Times': 1.0, 'WSJ': 1.0, 'The Wall Street Journal': 1.0, 'Associated Press': 0.95,
        'CNBC': 0.85, 'MarketWatch': 0.8, 'Barron\'s': 0.85, 'The Economist': 0.9, 'Federal Reserve': 1.0, 'Yahoo Finance': 0.7,
        'CoinDesk': 0.8, 'Fortune': 0.8, 'Business Insider': 0.7, 'Axios': 0.8, 'The New York Times': 0.95, 'Nikkei Asia': 0.9,
        '연합뉴스': 0.9, '연합인포맥스': 0.9, '한국경제': 0.85, '매일경제': 0.85, '서울경제': 0.8, '조선비즈': 0.8, '뉴스1': 0.8,
        '머니투데이': 0.8, '이데일리': 0.8, '파이낸셜뉴스': 0.8, '아시아경제': 0.75, '헤럴드경제': 0.75, 'KBS': 0.85, 'SBS Biz': 0.8,
        '한국경제TV': 0.75, '디지털투데이': 0.6, '블록미디어': 0.7, '코인데스크코리아': 0.7}
KW_EN = [(r'\bfed\b|federal reserve|fomc|powell', 3), (r'rate (cut|hike)|interest rate', 3), (r'inflation|\bcpi\b|\bpce\b|prices rose', 2.5),
         (r'jobs|payroll|unemployment|labor market', 2.2), (r'recession|slowdown|stagflation', 2.8), (r'treasur|yield|bond', 2),
         (r'tariff|trade war|trade deal|sanction', 2.4), (r'\bchina\b|beijing|xi jinping', 1.2), (r'earnings|revenue|guidance|profit', 1.4),
         (r'nvidia|apple|microsoft|tesla|amazon|alphabet|google|meta\b|openai|\bai\b', 1.3), (r'bitcoin|crypto|ether', 1.3),
         (r'oil|opec|crude|gold', 1.4), (r'crash|plunge|tumble|surge|soar|record high|all-time high|rout|sell-?off|rally', 2),
         (r's&p 500|nasdaq|dow jones|wall street|stocks', 1.8), (r'goldman|jpmorgan|blackrock|berkshire|buffett|burry|dimon|ackman|dalio', 1.4),
         (r'bankrupt|default|crisis|bailout|collapse', 2.5), (r'\bipo\b|merger|acquisition|buyback', 1.1), (r'dollar|yen|yuan|currency', 1.3)]
KW_KO = [(r'연준|FOMC|파월', 3), (r'금리', 2.4), (r'물가|CPI|인플레', 2.4), (r'고용|실업', 2), (r'경기\s?침체|불황', 2.8), (r'국채|채권', 1.8),
         (r'관세|무역', 2.3), (r'환율|원달러|달러', 1.8), (r'코스피|코스닥|증시|뉴욕증시', 2), (r'반도체|삼성전자|SK하이닉스|엔비디아', 1.5),
         (r'비트코인|가상자산|코인', 1.3), (r'급락|급등|폭락|폭등|사상 최고|최고치|최저치', 2), (r'외국인|기관', 1.2),
         (r'골드만|버리|버크셔|버핏|JP모건|블랙록', 1.4), (r'한국은행|기준금리', 2.2), (r'유가|금값|원자재', 1.4)]
# 공신력 있는 매체만 (구글 뉴스 검색 결과에 적용)
TRUSTED_EN = {'Reuters', 'Bloomberg', 'Bloomberg.com', 'The Wall Street Journal', 'WSJ', 'Financial Times', 'CNBC', 'Associated Press', 'AP News',
              'The New York Times', 'The Washington Post', 'MarketWatch', "Barron's", 'The Economist', 'Fortune', 'Axios', 'Business Insider',
              'Yahoo Finance', 'Nikkei Asia', 'CNN', 'CNN Business', 'BBC', 'The Guardian', 'Forbes', 'Morningstar', 'Investopedia',
              'CoinDesk', 'The Block', 'Decrypt', 'Politico', 'Bloomberg Law', 'Semafor', 'The Information', 'Federal Reserve',
              'Fox Business', 'ABC News', 'NBC News', 'CBS News', 'Kiplinger', 'Quartz', 'TechCrunch', 'The Verge', 'Wired', 'Al Jazeera',
              'South China Morning Post', 'Japan Times', 'Korea JoongAng Daily', 'The Korea Herald', 'The Korea Times', 'Yonhap News Agency'}
TRUSTED_KO = {'연합뉴스', '연합인포맥스', '한국경제', '매일경제', '서울경제', '조선비즈', '조선일보', '중앙일보', '동아일보', '한겨레', '경향신문',
              '머니투데이', '이데일리', '뉴스1', '뉴시스', '파이낸셜뉴스', '아시아경제', '헤럴드경제', '아주경제', '한국일보', '국민일보', '세계일보',
              'KBS', 'KBS 뉴스', 'MBC', 'MBC 뉴스', 'SBS', 'SBS 뉴스', 'YTN', 'JTBC', 'JTBC 뉴스', 'SBS Biz', '한국경제TV', '연합뉴스TV', 'MBN',
              '채널A', 'TV조선', '비즈워치', '디지털타임스', '전자신문', '매경이코노미', '이코노미스트', '한경비즈니스', '블록미디어',
              '코인데스크코리아', '디센터', '토큰포스트', '뉴스핌', '데일리안', '머니S', '한국금융신문', 'ZDNet Korea', '지디넷코리아', '블로터',
              '중앙SUNDAY', '서울신문', '문화일보', '내일신문', '노컷뉴스', '오마이뉴스', '프레시안', 'EBN', '이투데이', '비즈니스포스트'}
# 분류별로 제목에 꼭 들어가야 하는 말 (엉뚱한 기사 거르기)
CAT_NEED = {
    'people': r'goldman|burry|buffett|berkshire|jpmorgan|dimon|blackrock|fink|morgan stanley|ackman|dalio|cathie wood|druckenmiller|골드만|버리|버핏|버크셔|JP모건|다이먼|블랙록|래리 핑크|모건스탠리|애크먼|달리오|캐시 우드|드러켄밀러',
    'bonds': r'yield|treasur|bond|gilt|bund|jgb|금리|국채|채권|국고채|수익률',
    'commodities': r'oil|crude|opec|gold|silver|copper|natural gas|brent|wti|유가|원유|금값|금 가격|국제 금|은값|구리|원자재|천연가스',
    'crypto': r'bitcoin|crypto|ether|btc|stablecoin|solana|xrp|blockchain|비트코인|가상자산|코인|이더리움|스테이블|리플|솔라나|암호화폐',
    'tech': r'nvidia|apple|microsoft|tesla|alphabet|google|amazon|meta|openai|\bai\b|chip|semiconductor|엔비디아|애플|마이크로소프트|테슬라|구글|아마존|메타|반도체|AI',
    'world': r'관세|무역|제재|전쟁|휴전|정상회담|협상|중동|우크라|러시아|중국 경제|대만|선거|트럼프|유가|금리|환율|경제|증시|수출|공급망|OPEC|G7|G20',
}
STOP = set('the a an of to in on for and or with as at by from is are be its it this that after over amid into up down says say said new more than'.split())


def strip_html(s):
    s = re.sub(r'<[^>]+>', ' ', html.unescape(s or ''))
    return re.sub(r'\s+', ' ', s).strip()


def parse_feed(url, src, lang, cat, w):
    xml = get(url, timeout=20)
    items = re.findall(r'<item[\s>].*?</item>|<entry[\s>].*?</entry>', xml, re.S)
    out = []
    for it in items[:40]:
        def tag(name):
            m = re.search(rf'<{name}[^>]*>(.*?)</{name}>', it, re.S)
            if not m:
                return ''
            v = m.group(1)
            v = re.sub(r'^\s*<!\[CDATA\[(.*?)\]\]>\s*$', r'\1', v, flags=re.S)
            return v.strip()
        title = strip_html(tag('title'))
        link = tag('link') or (re.search(r'<link[^>]+href="([^"]+)"', it) or [None, ''])[1]
        link = html.unescape(strip_html(link))
        pub = tag('pubDate') or tag('published') or tag('updated') or tag('dc:date')
        try:
            dt = parsedate_to_datetime(pub) if pub and not re.match(r'\d{4}-', pub) else datetime.fromisoformat(pub.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = None
        source = src
        sm = re.search(r'<source[^>]*>(.*?)</source>', it, re.S)
        if not source and sm:
            source = strip_html(sm.group(1))
        if not src and ' - ' in title:  # 구글 뉴스: "제목 - 매체"
            title, _, tail = title.rpartition(' - ')
            source = source or tail
        if not title or not link:
            continue
        if dt and dt > NOW + timedelta(minutes=20):   # 한국 시간을 UTC로 잘못 적은 피드 보정
            dt = dt - timedelta(hours=9)
            if dt > NOW:
                dt = NOW
        source = (source or '').strip()
        if 'news.google.com' in url and source not in (TRUSTED_KO if lang == 'ko' else TRUSTED_EN):
            continue
        need = CAT_NEED.get(cat)
        if need and not re.search(need, title, re.I):
            continue
        desc = strip_html(tag('description') or tag('summary'))
        if desc.startswith(title[:30]) or 'news.google.com' in url:
            desc = ''
        out.append({'t': title, 'u': link, 's': (source or '').strip(), 'p': dt, 'lang': lang, 'c': cat, 'w': w, 'd': desc[:280]})
    return out


def norm_tokens(t, lang):
    if lang == 'ko':
        s = re.sub(r'[^\w가-힣]', '', t)
        return {s[i:i + 2] for i in range(len(s) - 1)}
    return {w for w in re.findall(r"[a-z0-9&']+", t.lower()) if w not in STOP and len(w) > 2}


def sim(a, b):
    if not a or not b:
        return 0
    return len(a & b) / len(a | b)


def score_item(x):
    kws = KW_KO if x['lang'] == 'ko' else KW_EN
    k = sum(w for pat, w in kws if re.search(pat, x['t'], re.I))
    hours = (NOW - x['p']).total_seconds() / 3600 if x['p'] else 12
    auth = AUTH.get(x['s'], 0.65) * x['w']
    return (1 + k) * auth * math.exp(-max(hours, 0) / 16)


def build_news():
    t0 = time.time()
    raw = pmap(lambda f: safe(lambda: parse_feed(*f), [], f'feed {f[1] or f[0][:70]}'), FEEDS, 10)
    items, seen = [], set()
    for L in raw:
        for x in L:
            if x['p'] and (NOW - x['p']) > timedelta(hours=48):   # 오래된 기사 제외 (WSJ 피드 등)
                continue
            key = re.sub(r'\W', '', x['t'].lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            x['id'] = hashlib.sha1(x['u'].encode()).hexdigest()[:10]
            x['tok'] = norm_tokens(x['t'], x['lang'])
            x['sc'] = score_item(x)
            items.append(x)
    # 비슷한 기사 묶기 (여러 매체가 다루면 중요)
    items.sort(key=lambda x: -x['sc'])
    clusters = []
    for x in items:
        for c in clusters:
            h = c['items'][0]
            if h['lang'] == x['lang'] and sim(h['tok'], x['tok']) >= (0.42 if x['lang'] == 'ko' else 0.4):
                c['items'].append(x)
                break
        else:
            clusters.append({'items': [x]})
    for c in clusters:
        srcs = {i['s'] for i in c['items']}
        c['n'] = len(srcs)
        c['sc'] = c['items'][0]['sc'] * (1 + 0.6 * (len(srcs) - 1))
    clusters.sort(key=lambda c: -c['sc'])
    log(f'news: {len(items)} items, {len(clusters)} clusters in {time.time() - t0:.1f}s')
    return clusters


# ---------------- 번역 (무료) ----------------
EN_FIX = [(r'\bedges? (lower|down)\b', 'slips slightly'), (r'\bedges? (higher|up)\b', 'rises slightly'), (r'\bticks? (up|higher)\b', 'rises slightly'),
          (r'\bticks? (down|lower)\b', 'dips slightly'), (r'\bWall St\b', 'Wall Street'), (r'\bFed\b', 'Federal Reserve')]
KO_FIX = [('했습니다', '했다'), ('됐습니다', '됐다'), ('되었습니다', '됐다'), ('졌습니다', '졌다'), ('합니다', '한다'), ('됩니다', '된다'),
          ('입니다', '이다'), ('있습니다', '있다'), ('없습니다', '없다'), ('습니다', '다'), ('연방준비제도', '연준'), ('연방 준비 은행', '연준')]


def tidy_ko(t):
    t = t.strip().rstrip('.')
    for a, b in KO_FIX:
        t = t.replace(a, b)
    return t


def gtx(texts):
    """무료 번역 (Google 번역 공개 엔드포인트 2가지). 실패하면 빈 결과."""
    fixed = []
    for k, t in texts:
        for pat, rep in EN_FIX:
            t = re.sub(pat, rep, t, flags=re.I)
        fixed.append((k, t))
    res = _gtx(fixed)
    return {k: tidy_ko(v) for k, v in res.items()}


def _gtx(texts):
    out = {}
    # 1) 여러 제목을 한 번에 (clients5)
    todo = list(texts)
    for i in range(0, len(todo), 16):
        chunk = todo[i:i + 16]
        try:
            qs = '&'.join('q=' + urllib.parse.quote(t.replace('\n', ' ')) for _, t in chunk)
            d = json.loads(get('https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl=ko&' + qs, timeout=20))
            if isinstance(d, list) and len(d) == len(chunk):
                for (k, _), v in zip(chunk, d):
                    tv = v[0] if isinstance(v, list) else v
                    if isinstance(tv, str) and tv.strip():
                        out[k] = tv.strip()
        except Exception as e:  # noqa
            log('!! clients5', type(e).__name__, str(e)[:100])
        time.sleep(0.4)
    texts = [(k, t) for k, t in texts if k not in out]
    if not texts:
        return out
    batch, size = [], 0
    def flush(b):
        if not b:
            return
        q = '\n'.join(t.replace('\n', ' ') for _, t in b)
        T = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ko&dt=t'
        post = lambda text: json.loads(get(T, data=urllib.parse.urlencode({'q': text}).encode(), timeout=20,
                                           headers={'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'}))
        try:
            d = post(q)
            res = ''.join(seg[0] for seg in d[0] if seg and seg[0]).split('\n')
            if len(res) == len(b):
                for (k, _), v in zip(b, res):
                    out[k] = v.strip()
            else:
                for k, t in b:
                    out[k] = ''.join(seg[0] for seg in post(t)[0] if seg and seg[0]).strip()
                    time.sleep(0.2)
        except Exception as e:  # noqa
            log('!! gtx', type(e).__name__, str(e)[:100])
        time.sleep(0.6)
    for k, t in texts:
        if size + len(t) > 2500:
            flush(batch)
            batch, size = [], 0
        batch.append((k, t))
        size += len(t) + 1
    flush(batch)
    return out


# ---------------- AI 요약 (GitHub Models, 무료) ----------------
GEM_MODELS = [m for m in [os.environ.get('AI_MODEL'), 'gemini-flash-latest', 'gemini-2.5-flash', 'gemini-flash-lite-latest',
                             'gemini-2.5-flash-lite', 'gemini-2.0-flash'] if m]
GEM_OK = []   # 이번 실행에서 성공한 모델 (다음 호출에 먼저 사용)


def ai_chat(prompt, max_tokens=4000):
    """AI 요약 (선택). 무료 Gemini API 키(GEMINI_API_KEY)가 있으면 사용, 없으면 None."""
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        return None
    sysmsg = ('너는 한국어로 글로벌 경제·증시 뉴스를 정리하는 애널리스트야. 주어진 자료에 있는 사실만 쓰고, 숫자나 사실을 지어내지 마. '
              '과장하지 말고 투자 권유는 하지 마. 자연스러운 한국어 뉴스 문체로 쓰고, 반드시 JSON만 출력해.')
    tried = set()
    for model in GEM_OK + GEM_MODELS:
        if model in tried:
            continue
        tried.add(model)
        gc = {'temperature': 0.3, 'maxOutputTokens': max_tokens, 'responseMimeType': 'application/json'}
        if '2.5' in model:
            gc['thinkingConfig'] = {'thinkingBudget': 0}   # 빠르게 (생각 단계 끄기)
        body = {'systemInstruction': {'parts': [{'text': sysmsg}]}, 'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'generationConfig': gc}
        try:
            req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                                         data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode('utf-8'))
            parts = ((d.get('candidates') or [{}])[0].get('content') or {}).get('parts') or []
            content = ''.join(p.get('text', '') for p in parts)
            m = re.search(r'\{.*\}', content, re.S)
            if not m:
                log('!! gemini empty', model, str(d)[:200])
                continue
            res = json.loads(m.group(0))
            if model not in GEM_OK:
                GEM_OK.insert(0, model)
            log('gemini ok', model)
            return res
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')[:200]
            log('!! gemini', model, e.code, msg)
        except Exception as e:  # noqa
            log('!! gemini', model, type(e).__name__, str(e)[:160])
    return None


# ---------- 기사 본문 (공개된 매체만) ----------
NO_FETCH = ('bloomberg.com', 'wsj.com', 'ft.com', 'economist.com', 'barrons.com', 'nytimes.com', 'reuters.com', 'news.google.com',
            'washingtonpost.com', 'businessinsider.com', 'marketwatch.com', 'theinformation.com')
BOILER = re.compile(r'(?i)copyright|all rights reserved|무단\s?전재|재배포\s?금지|구독|subscribe|newsletter|cookie|sign up|광고|제보|기자\s?=|@yna|ⓒ|©')


def article_text(url, limit=2200):
    host = urllib.parse.urlparse(url).netloc.lower()
    if not host or any(h in host for h in NO_FETCH):
        return ''
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8'})
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read(800_000)
            cs = r.headers.get_content_charset() or ''
        if not cs:
            m = re.search(rb'charset=["\']?([\w-]+)', raw[:4000])
            cs = m.group(1).decode() if m else 'utf-8'
        h = raw.decode(cs, errors='replace')
    except Exception:
        return ''
    h = re.sub(r'(?is)<(script|style|noscript|figure|figcaption|aside|nav|footer|header|form)[^>]*>.*?</\1>', ' ', h)
    paras = [strip_html(p) for p in re.findall(r'(?is)<p[^>]*>(.*?)</p>', h)]
    paras = [p for p in paras if len(p) >= 40 and not BOILER.search(p)]
    return ' '.join(paras)[:limit]


def sentences(text, lang):
    text = re.sub(r'\s+', ' ', text or '').strip()
    if not text:
        return []
    parts = re.split(r'(?<=다\.)\s+|(?<=[.!?])\s+(?=[A-Z가-힣"“‘\(])', text) if lang == 'ko' else re.split(r'(?<=[.!?])\s+(?=[A-Z"“‘\(])', text)
    bad = re.compile(r'(?i)day[- ]ahead|newsletter|sign up|click here|read more|이 기사|관련 기사|사진=|영상=|▶')
    return [p.strip() for p in parts if (30 if lang == 'ko' else 50) <= len(p.strip()) <= 260 and not bad.search(p)]


def ai_summarize(cls):
    """주요 뉴스 기사별 3~5줄 요약 (Gemini)"""
    blocks = []
    for c in cls:
        h = c['items'][0]
        ev = [f"제목: {h['t']} ({h['s']})"]
        if h['d']:
            ev.append(f"설명: {h['d'][:300]}")
        if c.get('text'):
            ev.append(f"본문 일부: {c['text'][:1800]}")
        for o in c['items'][1:4]:
            ev.append(f"같은 사건 다른 매체: {o['s']} — {o['t']}" + (f" / {o['d'][:160]}" if o['d'] else ''))
        blocks.append(f"[id={h['id']}]\n" + '\n'.join(ev))
    prompt = f"""다음은 지금({NOW.astimezone(KST):%m월 %d일 %H:%M} KST) 주요 경제·증시 뉴스야. 각 뉴스를 한국어로 정리해줘.

규칙
- title: 자연스러운 한국어 뉴스 제목 (35자 이내, 고유명사는 한국에서 쓰는 표기)
- lines: 3~5개. 각 1문장(70자 이내). 순서: 무슨 일인지 → 핵심 숫자·주체 → 배경·이유 → 시장·투자자에게 의미
- why: 투자자에게 왜 중요한지 1문장 (40자 이내)
- 자료에 없는 숫자·사실은 절대 지어내지 마. 자료가 제목뿐이면 확실한 내용만 3줄로.
- 문체는 '~했다', '~이다' 같은 뉴스체

JSON 형식: {{"items": [{{"id": "id 그대로", "title": "...", "lines": ["...", "..."], "why": "..."}}]}}

뉴스
{chr(10).join(blocks)}"""
    res = ai_chat(prompt, max_tokens=6000)
    out = {}
    for it in (res or {}).get('items', []):
        if not isinstance(it, dict) or not it.get('id'):
            continue
        lines = [str(l).strip() for l in (it.get('lines') or []) if str(l).strip()][:5]
        if len(lines) >= 2:
            out[str(it['id']).strip()] = {'title': str(it.get('title') or '').strip(), 'lines': lines, 'why': str(it.get('why') or '').strip()}
    return out


def fmt_pct(v):
    return '-' if v is None else f'{v:+.2f}%'


def market_digest(m):
    """시장 데이터를 한 줄씩 요약 (AI 입력 + AI 없을 때 화면용)"""
    L = []
    W = {x['id']: x for x in m.get('world', [])}
    if '.INX' in W:
        L.append(f"미국: S&P500 {fmt_pct(W['.INX']['pct'])}, 나스닥 {fmt_pct(W.get('.IXIC', {}).get('pct'))}, 다우 {fmt_pct(W.get('.DJI', {}).get('pct'))}, 반도체(SOX) {fmt_pct(W.get('.SOX', {}).get('pct'))}")
    kr = {x['id']: x for x in m['kr'].get('indices', [])}
    if 'KOSPI' in kr:
        inv = (m['kr'].get('investor') or {}).get('KOSPI') or {}
        flow = f" · 외국인 {inv.get('foreign'):+,.0f}억, 기관 {inv.get('inst'):+,.0f}억, 개인 {inv.get('personal'):+,.0f}억" if inv.get('foreign') is not None else ''
        L.append(f"한국: 코스피 {kr['KOSPI']['price']:,.2f} ({fmt_pct(kr['KOSPI']['pct'])}), 코스닥 {kr.get('KOSDAQ', {}).get('price', 0):,.2f} ({fmt_pct(kr.get('KOSDAQ', {}).get('pct'))}){flow}")
    mac = m.get('macro', {})
    ex = {x['id']: x for x in mac.get('exchange', [])}
    bd = {x['id']: x for x in mac.get('bond', [])}
    en = {x['id']: x for x in mac.get('energy', [])}
    mt = {x['id']: x for x in mac.get('metals', [])}
    parts = []
    if 'FX_USDKRW' in ex:
        parts.append(f"원/달러 {ex['FX_USDKRW']['price']:,.1f}원({ex['FX_USDKRW']['chg']:+.1f})")
    if 'US10YT=RR' in bd:
        parts.append(f"미 10년물 {bd['US10YT=RR']['price']:.3f}%({bd['US10YT=RR']['chg'] * 100:+.1f}bp)")
    if 'CLcv1' in en:
        parts.append(f"WTI ${en['CLcv1']['price']:.2f}({fmt_pct(en['CLcv1']['pct'])})")
    if 'GCcv1' in mt:
        parts.append(f"금 ${mt['GCcv1']['price']:,.1f}({fmt_pct(mt['GCcv1']['pct'])})")
    if '.DXY' in ex:
        parts.append(f"달러인덱스 {ex['.DXY']['price']:.2f}")
    if parts:
        L.append('지표: ' + ', '.join(parts))
    cr = (m.get('crypto') or {}).get('coins') or []
    if cr:
        b = cr[0]
        L.append(f"코인: 비트코인 ${b['price']:,.0f} ({fmt_pct(b['pct'])})" + (f", 코인 공포탐욕 {m['crypto']['fg']['value']}" if m['crypto'].get('fg') else ''))
    us = (m.get('us') or {}).get('map') or []
    if us:
        mv = sorted(us[:40], key=lambda x: -abs(x['pct']))[:4]
        L.append('미국 대형주 큰 움직임: ' + ', '.join(f"{x['name']} {fmt_pct(x['pct'])}" for x in mv))
    km = (m['kr'].get('map') or [])
    if km:
        mv = sorted(km[:30], key=lambda x: -abs(x['pct'] or 0))[:4]
        L.append('국내 대형주 큰 움직임: ' + ', '.join(f"{x['name']} {fmt_pct(x['pct'])}" for x in mv))
    return L


def finish_news(clusters, market):
    # 화면용 기사 정리
    def item_out(x, n=1):
        return {'id': x['id'], 't': x['t'], 's': x['s'], 'u': x['u'], 'p': x['p'].astimezone(KST).isoformat(timespec='minutes') if x['p'] else None,
                'c': x['c'], 'lang': x['lang'], 'n': n, 'd': x['d'][:200]}
    top_cl, per_cat = [], {}
    quota = {'en': 5, 'ko': 3}
    for c in clusters:
        h = c['items'][0]
        if len(top_cl) >= 8:
            break
        if quota.get(h['lang'], 0) <= 0 or sum(1 for t in top_cl if t['items'][0]['c'] == h['c']) >= 2:
            continue
        quota[h['lang']] -= 1
        top_cl.append(c)
    for c in clusters:
        h = c['items'][0]
        per_cat.setdefault(h['c'], [])
        if len(per_cat[h['c']]) < 12:
            per_cat[h['c']].append(item_out(h, c['n']))
    for k in per_cat:  # 분류별은 최신순
        per_cat[k].sort(key=lambda x: x['p'] or '', reverse=True)
    top = [dict(item_out(c['items'][0], c['n']), also=[{'s': i['s'], 'u': i['u']} for i in c['items'][1:4]]) for c in top_cl]

    # 번역 대상 (영어 제목)
    all_items = top + [x for L in per_cat.values() for x in L]
    need = {x['id']: x['t'] for x in all_items if x['lang'] == 'en'}
    tr = CACHE['tr']
    sums = CACHE.setdefault('sum', {})     # AI 기사 요약 {id: {title, lines, why, at}}
    autos = CACHE.setdefault('auto', {})   # 자동 요약 (AI 없을 때) {id: [lines]}
    have_ai = bool(os.environ.get('GEMINI_API_KEY', '').strip())
    digest = market_digest(market) if market else []

    # (1) 주요 뉴스 본문 모으기 (공개된 매체만)
    def grab(c):
        for i in c['items'][:4]:
            t = article_text(i['u'])
            if len(t) >= 200:
                return t
        return ''
    need_text = [c for c in top_cl if c['items'][0]['id'] not in sums or (not have_ai and c['items'][0]['id'] not in autos)]
    for c, t in zip(need_text, pmap(grab, need_text, 6)):
        c['text'] = t

    # (2) 기사별 3~5줄 AI 요약 (새 기사만 → 무료 한도 아끼기)
    new = [c for c in top_cl if c['items'][0]['id'] not in sums]
    if have_ai and new:
        res = ai_summarize(new)
        for k, v in res.items():
            sums[k] = {**v, 'at': NOW.isoformat(timespec='minutes')}
        log(f'ai article summaries: {len(res)}/{len(new)}')

    # (3) AI가 없거나 실패한 기사는 본문 앞부분으로 자동 요약 (번역)
    todo = []
    for c in top_cl:
        h = c['items'][0]
        if h['id'] in sums or h['id'] in autos:
            continue
        sl = sentences(c.get('text') or '', h['lang'])[:3] or sentences(h['d'], h['lang'])[:3]
        if sl:
            todo.append((h, sl))
    tr_in = [(f"{h['id']}#{j}", line) for h, sl in todo if h['lang'] == 'en' for j, line in enumerate(sl)]
    tr_out = gtx(tr_in) if tr_in else {}
    for h, sl in todo:
        autos[h['id']] = [tr_out.get(f"{h['id']}#{j}", line) if h['lang'] == 'en' else line for j, line in enumerate(sl)]

    # (4) 핵심 요약 + 제목 번역 (1시간에 한 번, 주요 뉴스가 바뀌면)
    sig = hashlib.sha1(('|'.join(c['items'][0]['id'] for c in top_cl[:6]) + '|' + NOW.strftime('%Y%m%d%H')).encode()).hexdigest()[:12]
    ai = CACHE['ai'] if CACHE['ai'].get('sig') == sig else None
    if not ai and have_ai:
        lines = []
        for c in clusters[:22]:
            h = c['items'][0]
            s_ = sums.get(h['id'])
            lines.append(f"[{h['id']}] ({CAT_KO.get(h['c'], h['c'])}, {h['s']}, {c['n']}개 매체) {h['t']}" +
                         (f" — {' '.join(s_['lines'][:2])}" if s_ else (f" — {h['d'][:160]}" if h['d'] else '')))
        untranslated = [f"{k}: {v}" for k, v in need.items() if k not in tr][:70]
        prompt = f"""지금({NOW.astimezone(KST):%m월 %d일 %H:%M} KST) 시장 데이터와 주요 뉴스야.

[시장 데이터]
{chr(10).join(digest) or '없음'}

[뉴스 (id, 분류, 매체, 보도 매체 수, 제목 — 요약)]
{chr(10).join(lines)}

[번역할 영어 제목 (id: 제목)]
{chr(10).join(untranslated) or '없음'}

JSON으로만 답해:
{{
 "news_brief": ["오늘 꼭 알아야 할 글로벌 경제·증시 핵심 3~5개. 각 1문장, 숫자·주체를 구체적으로"],
 "market_brief": ["시장 데이터를 해석한 요약 3~4개. 각 1문장. 원인과 의미를 짧게"],
 "titles": {{"id": "한국어 제목"}}
}}"""
        ai = ai_chat(prompt)
        if ai:
            ai['sig'] = sig
            CACHE['ai'] = ai
            log('ai brief ok')
    if ai and isinstance(ai.get('titles'), dict):
        tr.update({k: v for k, v in ai['titles'].items() if isinstance(v, str) and v.strip()})
    rest = [(k, v) for k, v in need.items() if k not in tr]   # AI가 못 한 번역은 무료 번역으로
    if rest:
        tr.update(gtx(rest))
    for x in all_items:
        if x['lang'] == 'en' and tr.get(x['id']):
            x['tk'] = tr[x['id']]
    for x in top:
        sm = sums.get(x['id'])
        if sm:
            x['tk'] = sm.get('title') or x.get('tk')
            x['sum'], x['why'], x['sumType'] = sm['lines'], sm.get('why', ''), 'ai'
        elif autos.get(x['id']):
            x['sum'], x['sumType'] = autos[x['id']], 'auto'
    # 캐시 정리 (오래된 것부터)
    for store, keep in ((tr, 3000), (sums, 400), (autos, 400)):
        if len(store) > keep + 200:
            for k in list(store)[:len(store) - keep]:
                store.pop(k, None)
    return {'updated': NOW.astimezone(KST).isoformat(timespec='minutes'), 'ai': bool(ai) or any(x.get('sumType') == 'ai' for x in top),
            'brief': (ai or {}).get('news_brief') or [], 'marketBrief': (ai or {}).get('market_brief') or [], 'digest': digest,
            'top': top, 'cats': per_cat, 'catNames': CAT_KO}


def main():
    t0 = time.time()
    market = safe(build_market, None, 'market')
    if market:
        with open(os.path.join(OUT, 'market.json'), 'w', encoding='utf-8') as f:
            json.dump(market, f, ensure_ascii=False, separators=(',', ':'))
    clusters = safe(build_news, [], 'news')
    if clusters:
        news = safe(lambda: finish_news(clusters, market), None, 'finish news')
        if news:
            if market:  # 시장 요약은 증시 화면에서도 쓰도록
                market['brief'] = news['marketBrief']
                market['digest'] = news['digest']
                market['ai'] = news['ai']
                with open(os.path.join(OUT, 'market.json'), 'w', encoding='utf-8') as f:
                    json.dump(market, f, ensure_ascii=False, separators=(',', ':'))
            with open(os.path.join(OUT, 'news.json'), 'w', encoding='utf-8') as f:
                json.dump(news, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(OUT, 'cache.json'), 'w', encoding='utf-8') as f:
        json.dump(CACHE, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(OUT, 'log.txt'), 'w', encoding='utf-8') as f:
        f.write(f'{NOW.astimezone(KST).isoformat()}\n' + '\n'.join(LOG))
    log(f'done in {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
