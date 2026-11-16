#!/usr/bin/env python3
"""Public-only AION2 Global reward news fetcher for a static GitHub Pages site.

Only official publisher Steam announcements are authoritative for Drops.
Coupon discovery also examines the Japanese NCSOFT Lounge and public mirror
of the official AION2_JP account, labelled separately from verified NCSOFT sites.
No account credentials or game client access is used.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

UTC = dt.timezone.utc
JST = dt.timezone(dt.timedelta(hours=9))
BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'data' / 'rewards.json'
STEAM_API = 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=3393110&count=100&maxlength=0&format=json'
STEAM_RSS = 'https://steamcommunity.com/games/3393110/rss'
LOUNGE = 'https://lounge.plaync.com/'
X_MIRROR = 'https://teapawt.org/AION2_JP'
SOURCE_URL = 'https://x.com/AION2_JP'


def now_utc():
    return dt.datetime.now(tz=UTC)


def iso(value):
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def fetch(url: str, max_bytes: int = 3000000) -> str:
    req = Request(url, headers={'User-Agent': 'AION2-Support-Tool-Rewards/1.0 (public news only)', 'Accept': 'application/json, text/html, application/xml;q=0.9, */*;q=0.8'})
    with urlopen(req, timeout=18) as r:
        raw = r.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError('response too large')
    return raw.decode('utf-8', errors='replace')


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.suppress = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'svg'):
            self.suppress += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'tr', 'article', 'section'):
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'svg') and self.suppress:
            self.suppress -= 1
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'article', 'section'):
            self.text.append('\n')

    def handle_data(self, data):
        if not self.suppress:
            self.text.append(data)


def plain(value: str) -> str:
    value = re.sub(r'\[(?:/?(?:h[1-6]|b|i|u|list|url|quote|table|tr|td|p|spoiler))(?:=[^\]]+)?\]', '\n', value, flags=re.I)
    parser = TextExtractor()
    parser.feed(value)
    value = html.unescape(''.join(parser.text))
    value = re.sub(r'[\u200b\u200c\u200d\uFEFF\xa0]', ' ', value)
    value = re.sub(r'[ \t]+', ' ', value)
    return re.sub(r'\n{3,}', '\n\n', value).strip()


def norm_string(value, limit=220):
    return re.sub(r'[\x00-\x1f]+', ' ', str(value or '')).strip()[:limit]


MONTHS = {x.lower(): i + 1 for i, x in enumerate('January February March April May June July August September October November December'.split())}
MONTHS.update({x[:3].lower(): n for x, n in MONTHS.items()})
TZ_OFFSETS = {'PST':-8, 'PDT':-7, 'CET':1, 'CEST':2, 'UTC':0, 'JST':9}


def parse_drops_dates(section: str):
    """Return strictly parsed start/end from publisher's explicit event schedule."""
    # Japanese JST range, including two occurrences of year or second with year omitted
    jm = re.search(r'(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:[（(][^)）]{1,10}[)）])?\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:JST|日本時間)?\s*(?:～|〜|－|\-|to|→)\s*(?:(20\d{2})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:[（(][^)）]{1,10}[)）])?\s*(\d{1,2})\s*[:：]\s*(\d{2})\s*(?:JST|日本時間)?', section, flags=re.I)
    if jm:
        p = jm.groups(); yr = int(p[0] or now_utc().year)
        try:
            start = dt.datetime(yr, int(p[1]), int(p[2]), int(p[3]), int(p[4]), tzinfo=JST)
            endyr = int(p[5] or (yr + (int(p[6]) < int(p[1]) - 6)))
            end = dt.datetime(endyr, int(p[6]), int(p[7]), int(p[8]), int(p[9]), tzinfo=JST)
            if start < end < start + dt.timedelta(days=46):
                return iso(start), iso(end)
        except ValueError:
            pass
    # PST/CET/UTC: publisher typically uses "PST: November 4, 2026 at 06:00 - November 17, 2026 at 23:59"
    em = re.search(r'\b(PST|PDT|CET|CEST|UTC|JST)\s*[:：]\s*([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\s*(?:at\s*)?(\d{1,2}):(\d{2})\s*(?:-|–|—|to|through|～)\s*([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(20\d{2})\s*(?:at\s*)?(\d{1,2}):(\d{2})', section, flags=re.I)
    if em:
        p = em.groups(); zone=dt.timezone(dt.timedelta(hours=TZ_OFFSETS[p[0].upper()]));
        try:
            m1=MONTHS[p[1].lower()[:3]]; m2=MONTHS[p[6].lower()[:3]]
            start=dt.datetime(int(p[3]),m1,int(p[2]),int(p[4]),int(p[5]),tzinfo=zone)
            end=dt.datetime(int(p[8]),m2,int(p[7]),int(p[9]),int(p[10]),tzinfo=zone)
            if start < end < start + dt.timedelta(days=46): return iso(start),iso(end)
        except (KeyError, ValueError):
            pass
    return None, None


def pick_drops_block(body: str):
    """Take the text following the explicit Twitch Drops heading, not login-event dates."""
    matches = list(re.finditer(r'(?im)^[ \t]*(?:(?:#{1,6}|■|【|\[)\s*)?(?:Twitch[ \t]*Drops?|ツイッチ[ \t]*ドロップス?)(?:\s*[】\]])?[ \t]*$', body))
    for m in matches:
        # Avoid incidental link to Drops FAQ in unrelated article
        block=body[m.end():m.end()+3500]
        if not re.search(r'(?:Event\s+Schedule|イベント期間|開催期間|視聴時間|Watch\s*Time|PST\s*:|CET\s*:|JST)',block,re.I):
            continue
        start,end=parse_drops_dates(block[:2000])
        if start and end:
            return start,end
    return None,None


COUPON_RE = re.compile(r'(?:クーポン\s*(?:コード|番号)|coupon\s*(?:code|number)|redeem\s*code|gift\s*code)\s*(?:[:：=]|は|：|「|『|\s){0,18}[「『`"\']?([A-Za-z][A-Za-z0-9_\-]{5,39})', re.I)
STOPWORDS = {'AION2','COUPON','OFFICIAL','GLOBAL','REGION','GIVEAWAY','DEAVAS','DAEVAS','EVENT','REWARDS','PLEASE','UPDATE','ACCOUNT','TWITCH','DROPS','AVAILABLE','EXPIRED','REDEEM','THANKYOU','CODE','WELCOME','CODES','BEFORE','MAINTENANCE'}


def discover_coupons(text: str, source: str, source_kind: str, title: str = '') -> list[dict]:
    if not re.search(r'(?:coupon|クーポン|redeem code|gift code)',text,re.I): return []
    out=[]
    for m in COUPON_RE.finditer(text):
        code=m[1].upper()
        if code in STOPWORDS or not re.search(r'[A-Z]',code) or not re.search(r'\d',code) and len(code)<10:
            continue
        # Do not set an expiry timestamp from phrases such as "before maintenance".
        # It will remain visible with explicit verification warning.
        near=text[max(0,m.start()-400):m.end()+600]
        expiration = re.search(r'(?:(20\d{2})\s*年)?\s*(\d{1,2})月\s*(\d{1,2})日.{0,12}?メンテナンス(?:開始)?前',near)
        note='期限は公式告知で確認'
        expiry_value=None
        if expiration:
            yr=int(expiration[1] or now_utc().year)
            note=f'{yr}年{int(expiration[2])}月{int(expiration[3])}日 メンテナンス開始前（時刻未確定）'
        else:
            exact=re.search(r'(?:有効期限|使用期限|終了|expires?)[^\d]{0,20}(?:(20\d{2})年)?\s*(\d{1,2})月\s*(\d{1,2})日\s*(?:[（(][^）)]{1,8}[）)])?\s*(\d{1,2})[:：](\d{2})\s*(?:まで|JST)?',near,re.I)
            if exact:
                yr=int(exact[1] or now_utc().year)
                try:
                    expiry_value=iso(dt.datetime(yr,int(exact[2]),int(exact[3]),int(exact[4]),int(exact[5]),tzinfo=JST))
                    note='日本時間の公式記載による期限'
                except ValueError:pass
        # A third-party mirror cannot confirm undated or undelimited coupons.
        if source_kind=='mirror' and expiry_value is None and note=='期限は公式告知で確認':continue
        out.append({'code':code,'expires':expiry_value,'expiry_note':note,'region':'日本語グローバル版（対象サーバーは告知を確認）','reward':'公式告知で内容を確認','source':source,'confidence':('日本公式の公開告知' if source_kind=='lounge' else '公式アカウントの外部表示・要照合' if source_kind=='mirror' else 'AION2 Global公式掲示板' if source_kind=='nc_official' else 'Steam公式ニュース'),'published_title':norm_string(title,90)})
    return out


def nc_global_board():
    """Fetch publisher's Global news board, not KR/TW services.

    The endpoint is an unofficially documented public JSON interface and may
    change; a failure is recorded instead of being interpreted as 'no events'.
    """
    base='https://api-global-community.plaync.com/aion2_global'
    items=[]
    errors=[]
    for board,locale in [('notice_ja','ja-jp'),('notice_en','en-us')]:
        url=f'{base}/board/{board}/article/search/moreArticle?isVote=true&moreSize=30&moreDirection=BEFORE&previousArticleId=0'
        try:
            page=json.loads(fetch(url,max_bytes=1300000))
            news=page.get('contentList') or []
            if not isinstance(news,list) or not news:raise ValueError('no contentList')
            for n in news[:30]:
                id=str(n.get('id') or '')
                if not re.fullmatch(r'[a-zA-Z0-9]{10,40}',id):continue
                title=norm_string(n.get('title'),160)
                summary=plain(n.get('summary') or '')
                # Read full text only when relevant. The full article might embed
                # a Drops section inside a broader news announcement.
                if not re.search(r'(?:coupon|redeem|クーポン|Twitch|Drops|ルドラ|Ludra)',title+' '+summary,re.I):continue
                try:
                    detail=json.loads(fetch(f'{base}/board/{board}/article/{id}',max_bytes=1300000))
                    a=detail.get('article') or {}
                    body=((a.get('content') or {}).get('content') or '')
                    if not body:continue
                    items.append({'title':title,'contents':body,'url':f'https://aion2.plaync.com/{locale}/board/notice/view?articleId={id}','gid':id})
                except (ValueError,URLError,HTTPError,TimeoutError):continue
        except Exception as e:
            errors.append(f'{board}:{type(e).__name__}')
    if not items:
        raise RuntimeError('Global official boards unavailable or no readable relevant articles; '+', '.join(errors))
    return items,'AION2 Global公式掲示板 ('+str(len(items))+'件)'


def steam_news():
    try:
        result=json.loads(fetch(STEAM_API))
        news=result.get('appnews',{}).get('newsitems',[])
        if not isinstance(news,list) or not news:
            raise ValueError('official Steam API returned no items')
        return news,'Steam公式API'
    except Exception as first:
        import xml.etree.ElementTree as ET
        try:
            root=ET.fromstring(fetch(STEAM_RSS))
            items=[]
            for el in root.findall('.//item'):
                def val(tag): return el.findtext(tag) or ''
                items.append({'title':val('title'),'contents':val('description'),'url':val('link'),'gid':val('guid')})
            if not items:raise ValueError('empty official RSS')
            return items,'Steam公式RSS'
        except Exception as second:
            raise RuntimeError(f'API {type(first).__name__}: {first}; RSS {type(second).__name__}: {second}')


def parse_steam_items(items):
    drops=[];codes=[]
    for n in items:
        title=norm_string(n.get('title'),140)
        url=n.get('url') or ''
        if not url.startswith('https://') or not re.match(r'https://(?:steamcommunity\.com|store\.steampowered\.com|aion2\.plaync\.com)',url):
            continue
        text=plain(n.get('contents') or '')
        if len(text)<25:continue
        st, en=pick_drops_block(text)
        if st and en:
            # Content sometimes references old events; only keep last 60 days or near future
            endtime=dt.datetime.fromisoformat(en.replace('Z','+00:00'))
            if endtime>=now_utc()-dt.timedelta(days=50) and endtime<=now_utc()+dt.timedelta(days=90):
                drops.append({'id':'steam-'+re.sub(r'\W','',str(n.get('gid') or title))[:50], 'title':title or 'AION2 Twitch Drops', 'start':st, 'end':en, 'claim':None,'region':'AION2グローバル版','source':url,'rewards':[],'note':'視聴報酬・受取期限は公式告知で確認（自動収集）'})
        codes.extend(discover_coupons(text,url,'steam' if 'steamcommunity.com' in url else 'nc_official',title))
    return codes,drops


def find_feed_links(doc: str):
    seen=[]
    for uri in re.findall(r'(?:href|"url")\s*[=:]\s*["\']([^"\']*?/feed/\d+[^"\']*)["\']',doc,re.I):
        u=urljoin(LOUNGE,html.unescape(uri).replace('\\/','/'))
        if u.startswith('https://lounge.plaync.com/feed/') and u not in seen:seen.append(u)
    # Homepage SSR can list a game's feed URLs in embedded JSON instead of links
    for num in re.findall(r'(?:\\?/feed/)(\d{4,7})',doc):
        u=f'https://lounge.plaync.com/feed/{num}?country=JP&locale=ja-JP'
        if u not in seen:seen.append(u)
    return seen[:40]


def lounge_coupons():
    homepage=fetch(LOUNGE)
    links=find_feed_links(homepage)
    if not links:raise RuntimeError('No public Lounge feed links available')
    codes=[];checked=0
    for link in links[:25]:
        try:
            doc=fetch(link,max_bytes=900000)
            content=plain(doc)
            if not re.search(r'(?:AION\s*2|AION2|アイオン\s*2|アイオン２)',content[:6500],re.I):
                continue
            if not re.search(r'(?:クーポン|coupon|gift\s*code)',content,re.I):
                continue
            checked+=1
            codes+=discover_coupons(content,link,'lounge')
        except (URLError,HTTPError,TimeoutError,ValueError):
            continue
    return codes, f'PURPLE Lounge公開フィード ({len(links)}候補・{checked}関連)'


def mirror_coupons():
    # The mirror is NOT an official API. Its items are labelled as secondary,
    # and must never be considered independently confirmed as redeemable.
    text=plain(fetch(X_MIRROR,max_bytes=1500000))
    if not re.search(r'AION2_JP',text,re.I):
        raise ValueError('Official-account marker missing from mirror')
    # Only text around a coupon label; no unrelated code guesses.
    codes=discover_coupons(text,SOURCE_URL,'mirror','AION2_JP 公開投稿')
    return codes,'AION2_JP公開投稿（外部ミラー・参考）'


def main():
    old={}
    if OUT.exists():
        try:old=json.loads(OUT.read_text(encoding='utf-8'))
        except (OSError,ValueError):old={}
    oldcoupons=old.get('coupons',[]) if isinstance(old.get('coupons'),list) else []
    olddrops=old.get('drops',[]) if isinstance(old.get('drops'),list) else []
    sources=old.get('sources',{}) if isinstance(old.get('sources'),dict) else {}
    codes={x.get('code'):x for x in oldcoupons if isinstance(x,dict) and x.get('code')}
    drops={x.get('id'):x for x in olddrops if isinstance(x,dict) and x.get('id')}
    timestamp=iso(now_utc());good=False
    for name,fn in [('steam',lambda: (parse_steam_items(steam_news()[0]),'Steam公式API/RSS')),('nc_global',lambda: (parse_steam_items(nc_global_board()[0]),'AION2公式掲示板')),('lounge',lambda:(lounge_coupons(),'PURPLE Lounge')),('x_public',lambda:(mirror_coupons(),'AION2_JP公開投稿（外部表示）'))]:
        try:
            result,label=fn()
            if name in ('steam','nc_global'): cc,dd=result
            else: cc,dd=result,[]
            for c in cc:
                code=c['code']
                prev=codes.get(code,{})
                # Do not let the mirror override a publisher-official record.
                if prev.get('confidence') in ('Steam公式ニュース','日本公式の公開告知','AION2 Global公式掲示板') and name=='x_public':continue
                codes[code]={**prev,**c}
            for d in dd:
                same_id=next((id for id,old in drops.items() if old.get('start') and old.get('end') and abs((dt.datetime.fromisoformat(old['start'].replace('Z','+00:00'))-dt.datetime.fromisoformat(d['start'].replace('Z','+00:00'))).total_seconds())<300 and abs((dt.datetime.fromisoformat(old['end'].replace('Z','+00:00'))-dt.datetime.fromisoformat(d['end'].replace('Z','+00:00'))).total_seconds())<300),None)
                if same_id:
                    # Retain curated official reward list when newer article omits it.
                    old=drops[same_id]
                    drops[same_id]={**old,**{k:v for k,v in d.items() if k!='id' and (k!='rewards' or v)}}
                else:
                    drops[d['id']]={**drops.get(d['id'],{}),**d}
            sources[name]={'ok':True,'last_success_at':timestamp,'error':None,'found_coupons':len(cc),'found_drops':len(dd),'label':label}
            good=True
        except Exception as e:
            oldstatus=sources.get(name,{})
            sources[name]={**oldstatus,'ok':False,'error':norm_string(str(e),180)}
    # Bounded public data; keep seeded/current records and recent campaigns, but
    # suppress old expired news in the frontend instead of inventing new dates.
    coupons=list(codes.values())[-80:]
    drop_list=list(drops.values())[-35:]
    output={'schema':'aion2-rewards-v2','updated_at':timestamp if good else old.get('updated_at'), 'attempted_at':timestamp,'sources':sources,'coupons':coupons,'drops':drop_list}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'rewards: {len(coupons)} coupon candidates, {len(drop_list)} drop events, sources: '+', '.join(f'{k}={"ok" if v.get("ok") else "error"}' for k,v in sources.items()))
    if not good:
        print('All providers failed; retaining previous snapshot (not claiming fresh data).',file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
