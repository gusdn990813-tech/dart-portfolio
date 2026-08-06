# 대시보드 미리보기용 가짜 공시 데이터 생성기 (실제 데이터 아님)
import json, random, sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0,'scripts')
from rules import classify
KST=timezone(timedelta(hours=9)); now=datetime.now(KST)
corps=[("005930","삼성전자","반도체","코스피"),("000660","SK하이닉스","반도체","코스피"),
       ("373220","LG에너지솔루션","2차전지","코스피"),("005380","현대차","자동차","코스피"),
       ("035420","NAVER","플랫폼","코스피"),("068270","셀트리온","바이오","코스피")]
titles=["유상증자결정","전환사채권발행결정","분기보고서 (2026.06)","매출액또는손익구조30%(대규모법인은15%)이상변동",
 "단일판매ㆍ공급계약체결","최대주주변경","주식등의대량보유상황보고서(일반)","현금ㆍ현물배당결정",
 "자기주식취득결정","임원ㆍ주요주주특정증권등소유상황보고서","기타경영사항(자율공시)","[기재정정]유상증자결정",
 "타법인주식및출자증권취득결정","신규시설투자등","주주총회소집결의","감사보고서제출","소송등의제기"]
items=[]; n=0
random.seed(7)
for d in range(0,90):
    day=(now-timedelta(days=d)).strftime("%Y-%m-%d")
    for _ in range(random.randint(0,4)):
        c=random.choice(corps); t=random.choice(titles); cat,lv=classify(t); n+=1
        items.append({"rcept_no":f"2026{n:014d}","date":day,"ticker":c[0],"name":c[1],"group":c[2],
        "kind":"보유","market":c[3],"title":t,"filer":c[1],"remark":"","category":cat,"level":lv,
        "url":f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=2026{n:014d}","is_new": d==0})
items.sort(key=lambda x:(x["date"],x["rcept_no"]),reverse=True)
json.dump({"items":items},open("sample-data/disclosures.json","w"),ensure_ascii=False,indent=1)
json.dump({"updated_at":now.isoformat(),"updated_at_display":now.strftime("%Y-%m-%d %H:%M KST")+" (샘플 데이터)",
 "range":{"from":"","to":"","lookback_days":90,"keep_days":365},"total":len(items),"new_count":sum(i["is_new"] for i in items),
 "unresolved_tickers":[],"holdings":[{"ticker":c[0],"label":c[1],"group":c[2],"kind":"보유"} for c in corps]},
 open("sample-data/meta.json","w"),ensure_ascii=False,indent=1)
print("mock items:",len(items))
