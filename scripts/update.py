"""Weekly data refresh for the ACCESS Energy Finance and Access Tracker.

Pulls public data and rewrites data.json. If a source fails, the previous
values for that source are kept and the failure is recorded in meta.
Sources: World Bank WDI API, World Bank Projects API, AfDB IATI data (d-portal),
Climate Watch NDC API, AfDB Mission 300 tracker (MapAfrica JSON) and the
World Bank Group Mission 300 Progress Portal (Power BI, read with Playwright).
"""
import json, re, sys, datetime, traceback, pathlib
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data.json"
TODAY = datetime.date.today().isoformat()
UA = {"User-Agent": "energy-tracker-bot/1.0"}
def sec(p, i):
    s = p.get(f"sector{i}")
    return s if isinstance(s, dict) else {}

# ISO3, ISO2, display name, World Bank projects API name
SSA = [("AGO","AO","Angola","Angola"),("BEN","BJ","Benin","Benin"),("BWA","BW","Botswana","Botswana"),("BFA","BF","Burkina Faso","Burkina Faso"),("BDI","BI","Burundi","Burundi"),("CPV","CV","Cabo Verde","Cabo Verde"),("CMR","CM","Cameroon","Cameroon"),("CAF","CF","Central African Rep.","Central African Republic"),("TCD","TD","Chad","Chad"),("COM","KM","Comoros","Comoros"),("COD","CD","DR Congo","Congo, Democratic Republic of"),("COG","CG","Rep. of Congo","Congo, Republic of"),("CIV","CI","Côte d'Ivoire","Cote d'Ivoire"),("GNQ","GQ","Equatorial Guinea","Equatorial Guinea"),("ERI","ER","Eritrea","Eritrea"),("SWZ","SZ","Eswatini","Eswatini"),("ETH","ET","Ethiopia","Ethiopia"),("GAB","GA","Gabon","Gabon"),("GMB","GM","The Gambia","Gambia, The"),("GHA","GH","Ghana","Ghana"),("GIN","GN","Guinea","Guinea"),("GNB","GW","Guinea-Bissau","Guinea-Bissau"),("KEN","KE","Kenya","Kenya"),("LSO","LS","Lesotho","Lesotho"),("LBR","LR","Liberia","Liberia"),("MDG","MG","Madagascar","Madagascar"),("MWI","MW","Malawi","Malawi"),("MLI","ML","Mali","Mali"),("MRT","MR","Mauritania","Mauritania"),("MUS","MU","Mauritius","Mauritius"),("MOZ","MZ","Mozambique","Mozambique"),("NAM","NA","Namibia","Namibia"),("NER","NE","Niger","Niger"),("NGA","NG","Nigeria","Nigeria"),("RWA","RW","Rwanda","Rwanda"),("STP","ST","São Tomé and Príncipe","Sao Tome and Principe"),("SEN","SN","Senegal","Senegal"),("SYC","SC","Seychelles","Seychelles"),("SLE","SL","Sierra Leone","Sierra Leone"),("SOM","SO","Somalia","Somalia"),("ZAF","ZA","South Africa","South Africa"),("SSD","SS","South Sudan","South Sudan"),("SDN","SD","Sudan","Sudan"),("TZA","TZ","Tanzania","Tanzania"),("TGO","TG","Togo","Togo"),("UGA","UG","Uganda","Uganda"),("ZMB","ZM","Zambia","Zambia"),("ZWE","ZW","Zimbabwe","Zimbabwe")]
NORTH = ["DZA","DJI","EGY","LBY","MAR","TUN"]
NORTH2 = ["DZ","DJ","EG","LY","MA","TN"]
AF54 = [c[0] for c in SSA] + NORTH
ALIASES = {"Democratic Republic of the Congo":"DR Congo","Democratic Republic of Congo":"DR Congo","Republic of Congo":"Rep. of Congo","Congo":"Rep. of Congo","Cote d'Ivoire":"Côte d'Ivoire","Côte d’Ivoire":"Côte d'Ivoire","Gambia":"The Gambia","Sao Tome and Principe":"São Tomé and Príncipe","Central African Republic":"Central African Rep."}
NAMES = {c[2] for c in SSA}
def norm(n):
    n = n.strip()
    return ALIASES.get(n, n)

def get(url, **kw):
    r = requests.get(url, headers=UA, timeout=90, **kw)
    r.raise_for_status()
    return r

# ---------------- World Bank WDI ----------------
def wdi():
    codes = ";".join([c[0] for c in SSA] + ["SSF"])
    out = {}
    for ind in ["EG.ELC.ACCS.ZS","EG.ELC.ACCS.RU.ZS","EG.ELC.ACCS.UR.ZS","EG.CFT.ACCS.ZS","SP.POP.TOTL"]:
        j = get(f"https://api.worldbank.org/v2/country/{codes}/indicator/{ind}?format=json&date=2015:2035&per_page=20000").json()
        d = {}
        for x in j[1] or []:
            if x["value"] is not None:
                d.setdefault(x["countryiso3code"], {})[int(x["date"])] = x["value"]
        out[ind] = d
    ssf = out["EG.ELC.ACCS.ZS"]["SSF"]
    years = sorted(y for y in ssf if y >= 2015 and all(y in out[i].get("SSF", {}) for i in out))
    S = lambda i: [round(out[i]["SSF"][y], 1) for y in years]
    pop = [out["SP.POP.TOTL"]["SSF"][y] for y in years]
    acc = dict(years=years, a=S("EG.ELC.ACCS.ZS"), r=S("EG.ELC.ACCS.RU.ZS"), u=S("EG.ELC.ACCS.UR.ZS"), c=S("EG.CFT.ACCS.ZS"))
    acc["noE"] = [round(p*(100-a)/100/1e6) for p, a in zip(pop, acc["a"])]
    acc["noC"] = [round(p*(100-c)/100/1e6) for p, c in zip(pop, acc["c"])]
    ctry = {}
    for i3, *_ in SSA:
        a = out["EG.ELC.ACCS.ZS"].get(i3, {}); c = out["EG.CFT.ACCS.ZS"].get(i3, {})
        ly = max(a) if a else None; lc = max(c) if c else None
        ctry[i3] = dict(a15=round(a.get(2015, 0), 1), aL=round(a[ly], 1) if ly else None, aY=ly,
                        c15=round(c.get(2015, 0)), cL=round(c[lc]) if lc else None)
    return acc, ctry

# ---------------- World Bank projects ----------------
def wb_cat(n):
    if n.startswith("Renewable"): return 0
    if re.search(r"Non-Renewable Energy Generation|Oil and Gas", n): return 1
    if "Transmission and Distribution" in n: return 2
    if "Public Administration - Energy" in n: return 3
    if re.search(r"Other Energy and Extractives|^Power$", n): return 4
    return None
ACC = re.compile(r"access|electrif|off-grid|offgrid|mini-grid|minigrid|last mile|rural|clean cooking|cookstove|solar home|lighting|peri-urban|energy inclusion", re.I)
num = lambda s: float(str(s or "0").replace(",", "") or 0)

def wb_projects():
    fl = "id,project_name,countryshortname,boardapprovaldate,totalcommamt,ibrdcommamt,idacommamt,sector1,sector2,sector3,sector4,sector5,lendinginstr,status,regionname"
    allp, coverage = [], {}
    for reg in ["Eastern and Southern Africa", "Western and Central Africa", "Africa"]:
        os_ = 0
        while True:
            j = get("https://search.worldbank.org/api/v2/projects", params=dict(format="json", rows=500, os=os_, fl=fl, regionname_exact=reg)).json()
            p = list((j.get("projects") or {}).values())
            allp += p
            if len(p) < 500: break
            os_ += 500
    for p in allp:
        y = (p.get("boardapprovaldate") or "")[:4]
        if y >= "2015":
            c = coverage.setdefault(y, [0, 0]); c[0] += 1
            if sec(p, 1).get("Name"): c[1] += 1
    good = [y for y, (n, s) in coverage.items() if n and s / n >= 0.8]
    last = max(good) if good else "2023"
    years, ctry, fossil, accp = {}, {}, [], []
    for p in allp:
        y = (p.get("boardapprovaldate") or "")[:4]
        if not ("2015" <= y <= last) or p.get("status") == "Dropped": continue
        T = num(p.get("totalcommamt"))
        if not T: continue
        e = [0.0]*5
        for i in range(1, 6):
            s = sec(p, i)
            k = wb_cat(s.get("Name") or "")
            if k is not None: e[k] += T * (s.get("Percent") or 0) / 100
        es = sum(e)
        if not es: continue
        yy = years.setdefault(y, [0.0]*8)
        for k in range(5): yy[k] += e[k]
        if ACC.search(p["project_name"]): yy[5] += es; accp.append(["World Bank", p["project_name"], p.get("countryshortname"), int(y), round(es/1e6), None])
        yy[6] += num(p.get("idacommamt")) * es / T; yy[7] += num(p.get("ibrdcommamt")) * es / T
        nm = norm(p.get("countryshortname") or "")
        ctry[nm] = ctry.get(nm, 0) + es
        if e[1] > 0:
            kind = "Oil & gas sector share in a budget-support loan" if "Development Policy" in (p.get("lendinginstr") or "") else "Fossil generation / oil & gas"
            fossil.append(["World Bank", p["project_name"], p.get("countryshortname"), int(y), round(e[1]/1e6), kind])
    years = {y: [round(v/1e6) for v in vals] for y, vals in sorted(years.items())}
    cov = {y: round(100*s/n) for y, (n, s) in sorted(coverage.items())}
    return dict(years=years, last=last, coverage=cov, ctry={k: round(v/1e6) for k, v in ctry.items()}), fossil, accp

# ---------------- AfDB via IATI (d-portal) ----------------
def af_cls(t):
    if re.search(r"azito|ciprel|malicounda|\bLNG\b|\bgas power|\bgas\b(?! insulated)|\boil\b|refiner|petrol|coal|diesel|\bHFO\b|dual fuel", t, re.I): return 1
    if re.search(r"solar|wind|hydro|hidro|geotherm|renewable|desert[- ]to[- ]power|biomass|\bPV\b|kariba|bujagali|cahora|GETFIT|energy inclusion|energy access platform|LEAF|off-grid|dam\b", t, re.I): return 0
    if re.search(r"transmission|interconnect|distribution|cable|grid|\bline\b|substation|switchgear|kv\b|last mile|electri|river basin|access", t, re.I): return 2
    if re.search(r"reform|governance|institution|efficien|support|technical assistance|study|studies|capacity|policy|regulat|digiti|excellence|accelera", t, re.I): return 3
    return 4

I2N = {c[1]: c[2] for c in SSA}
def afdb_iati():
    j = get("https://d-portal.org/q.json", params={"from": "act,sector", "limit": "-1", "select": "aid,title,day_start,commitment,spend,sector_code,sector_percent", "reporting_ref": "XM-DAC-46002"}).json()
    rows = [x for x in j["rows"] if re.match(r"^(23|3226)", str(x["sector_code"])) and (x["day_start"] or 0) >= 16436]
    years, ctry, fossil, accp = {}, {}, [], []
    tot = gen = spent = nos = mism = n = 0
    this_year = datetime.date.today().year
    for x in rows:
        cc = x["aid"].split("-")[2]
        y = datetime.date(1970, 1, 1) + datetime.timedelta(days=x["day_start"])
        y = y.year
        if cc in NORTH2 or y > this_year: continue
        f = (x["sector_percent"] or 100) / 100
        t = re.sub(r"\s+", " ", x["title"]).strip()
        com = (x["commitment"] or 0) * f / 1e6; sp = (x["spend"] or 0) * f / 1e6
        k = af_cls(t)
        yy = years.setdefault(str(y), [0.0]*7)
        yy[k] += com; yy[6] += sp
        if ACC.search(t): yy[5] += com; accp.append(["AfDB", re.sub(r"^[^-–]+[-–]\s*", "", t)[:90], I2N.get(cc, "Multi-country"), y, round(com), round(sp)])
        if k == 1: fossil.append(["AfDB", re.sub(r"^[^-–]+[-–]\s*", "", t)[:90], I2N.get(cc, "Multi-country"), y, round(com), "Fossil (title screen)"])
        ctry[cc] = ctry.get(cc, 0) + com
        tot += com; spent += sp; n += 1
        if str(x["sector_code"]) == "23111": gen += com
        if not sp: nos += 1
        if str(x["sector_code"]) in ("23310", "23320") and k == 0: mism += 1
    years = {y: [round(v) for v in vals] for y, vals in sorted(years.items())}
    gaps = dict(genericPct=round(100*gen/tot) if tot else None, mismatch=mism, spentPct=round(100*spent/tot) if tot else None, noSpendPct=round(100*nos/n) if n else None, total=round(tot), spent=round(spent))
    return dict(years=years, ctry={k: round(v) for k, v in ctry.items()}), fossil, accp, gaps

# ---------------- Climate Watch NDCs ----------------
def climatewatch():
    ids = "submission,submission_date,conditional_financial_requirements,btr"
    j = get("https://www.climatewatchdata.org/api/v1/ndcs", params={"indicators": ids}).json()
    out = {}
    for ind in j["indicators"]:
        for c in AF54:
            l = (ind.get("locations") or {}).get(c)
            if l:
                v = (l[0] if isinstance(l, list) else l).get("value")
                out.setdefault(c, {})[ind["slug"]] = v
    res = {}
    for c in AF54:
        o = out.get(c, {})
        cn = o.get("conditional_financial_requirements")
        try: cn = float(str(cn).replace("$", "").replace(",", ""))
        except Exception: cn = None
        res[c] = dict(ndc=o.get("submission") or "No Document Submitted", btr=bool(o.get("btr")) and "No Document" not in str(o.get("btr")), cn=cn)
    return res

# ---------------- AfDB Mission 300 tracker ----------------
def afdb_m300():
    r = get("https://mapafrica.afdb.org/api/results/m300/all.json").json()
    G = [x for x in r if x.get("Global/Milestone") == "Global"]
    ppl = "People provided with access to electricity"
    mode, conn, P = {}, {}, {}
    for x in G:
        d = x.get("Expected/Delivered") == "Delivered"
        if d and x.get("Sub-Sub-indicators") == "Total": mode[x["Sub-indicators"]] = mode.get(x["Sub-indicators"], 0) + (x.get(ppl) or 0)
        if d and x.get("Sub-indicators") == "Total": conn[x["Sub-Sub-indicators"]] = conn.get(x["Sub-Sub-indicators"], 0) + (x.get("Number of electricity connections") or 0)
        if x.get("Sub-indicators") == "Total" and x.get("Sub-Sub-indicators") == "Total":
            p = P.setdefault(x["Project Code"], [x["Country"], re.sub(r"^[^-–]+[-–]\s*", "", x["Project name"])[:90], 0, 0, 0, datetime.datetime.utcfromtimestamp(x["Approval Date"]/1000).year if x.get("Approval Date") else None])
            v = x.get(ppl) or 0
            if d: p[2] = max(p[2], round(v))
            else: p[3] = max(p[3], round(v))
            p[4] = max(p[4], round((x.get("BANK's Financing [ADB/ADF/NTF]") or 0)/1e6))
    ps = [p for p in P.values() if p[2] or p[3]]
    delivered = sum(p[2] for p in ps); expected = sum(p[3] for p in ps)
    pre = sum(p[2] for p in ps if p[5] and p[5] < 2023)
    return dict(asof=TODAY, connected=round(delivered), expected=round(expected), projects=len(ps), finance=sum(p[4] for p in ps),
                ongrid=round(mode.get("On-grid", 0)), offgrid=round(mode.get("Off-grid", 0)), minigrid=round(mode.get("Mini-grid", 0)),
                connHH=round(conn.get("Households", 0)), connBiz=round(conn.get("Businesses", 0)), connPub=round(conn.get("Public services", 0)),
                prePct=round(100*pre/delivered) if delivered else None, list=sorted(ps, key=lambda p: -p[3]))

# ---------------- World Bank Group Mission 300 portal (Power BI) ----------------
def mnum(s):
    s = s.replace(",", "").strip()
    m = 1e6 if s.endswith("M") else 1e3 if s.endswith("K") else 1
    return round(float(s.rstrip("MK")) * m)

def wbg_m300():
    from playwright.sync_api import sync_playwright
    res = {"asof": TODAY}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        pg.goto("https://www.worldbank.org/ext/en/energizingafrica/progress-portal", wait_until="domcontentloaded", timeout=120000)
        pg.wait_for_selector("iframe[src*='powerbi']", state="attached", timeout=90000)
        src = pg.locator("iframe[src*='powerbi']").first.get_attribute("src")
        pg.goto(src, wait_until="domcontentloaded", timeout=120000)
        pg.wait_for_function("document.body.innerText.includes('People connected since')", timeout=90000); pg.wait_for_timeout(5000)
        t = pg.inner_text("body")
        m = re.search(r"([\d.]+)\s*Million\s*\n+\s*People connected since", t)
        res["connected"] = round(float(m.group(1)) * 1e6)
        d = re.search(r"Data as of ([A-Za-z]+ \d{4})", t); res["dataAsOf"] = d.group(1) if d else None
        fy = re.findall(r"\n(FY\d\d)\n", t)
        vals = re.findall(r"\n(\d+)M\n", t)
        # bar labels appear after the axis; the last value is the total
        if fy and len(vals) >= len(fy) + 1:
            v = [int(x) for x in vals[-(len(fy)+1):-1]]
            res["byFY"] = [[f, x] for f, x in zip(fy, v)]
        def growth(g):
            for key, lab in [("biz", "Businesses provided with access to electricity"), ("social", "Social and public institutions provided with access to electricity")]:
                m = re.search(r"([\d,]+)\n" + re.escape(lab), g)
                if m: res[key] = int(m.group(1).replace(",", ""))
        def cofin(f):
            m = re.search(r"\n([\d.]+)\n\nTop Co-financiers", f)
            if m: res["cofinBn"] = float(m.group(1))
        def projects(_):
            vp = pg.locator(".mid-viewport").first
            vp.evaluate("e => e.scrollTop = 0"); pg.wait_for_timeout(1500)
            chunks = []
            for _i in range(80):
                chunks.append(vp.inner_text())
                before = vp.evaluate("e => e.scrollTop")
                vp.evaluate("e => e.scrollTop += 350"); pg.wait_for_timeout(900)
                if vp.evaluate("e => e.scrollTop") == before: break
            merged = chunks[0].split("\n")
            for c in chunks[1:]:
                a = c.split("\n"); k = 0
                for o in range(min(len(a), len(merged)), 0, -1):
                    if a[:o] == merged[-o:]: k = o; break
                merged += a[k:]
            L = [x.strip() for x in merged if x.strip()]
            rows = []; i = 0
            while i + 3 < len(L):
                c, p, a, tg = L[i:i+4]
                if re.fullmatch(r"[\d.,]+[MK]?", a) and re.fullmatch(r"[\d.,]+[MK]?", tg):
                    rows.append([norm(c), p, mnum(a), mnum(tg)]); i += 4
                else:
                    i += 1
            if len(rows) > 20: res["projects"] = rows
        def compacts():
            pg.goto("https://www.worldbank.org/ext/en/energizingafrica/national-energy-compacts", wait_until="domcontentloaded", timeout=120000)
            pg.wait_for_timeout(6000)
            ct = pg.inner_text("main")
            comp = {}
            for m in re.finditer(r"\n([A-Z][^\n]{2,40})\n\n([A-Z][a-z]+ \d{4})\n\nDownload(\n\nProgress)?", ct):
                comp[norm(m.group(1))] = m.group(2)[:3] + " " + m.group(2)[-4:] + ("*" if m.group(3) else "")
            if len(comp) > 10: res["compacts"] = comp
        def tab(name):
            pg.evaluate("""n => { const els = [...document.querySelectorAll('*')].filter(e => e.children.length === 0 && e.textContent.trim() === n);
                const el = els[els.length - 1]; if (!el) throw new Error('tab not found: ' + n);
                el.dispatchEvent(new MouseEvent('click', {bubbles: true})); }""", name)
            pg.wait_for_timeout(9000)
            return pg.inner_text("body")
        def part(fn):
            try: fn()
            except Exception as e: print("wbg_m300 part failed:", e)
        part(lambda: growth(tab("Powering Growth")))
        part(lambda: cofin(tab("Financing & Mobilization")))
        part(lambda: projects(tab("Project Overview")))
        part(compacts)
        b.close()
    if "connected" not in res: raise RuntimeError("headline not found")
    return res

# ---------------- assemble ----------------
def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    D = dict(prev); meta = dict(prev.get("meta", {})); errors = []
    def run(key, fn):
        try:
            v = fn(); meta[key] = {"updated": TODAY, "ok": True}; return v
        except Exception as e:
            traceback.print_exc(); errors.append(f"{key}: {e}")
            meta[key] = {**meta.get(key, {}), "ok": False, "lastError": str(e)[:200], "tried": TODAY}
            return None
    w = run("wdi", wdi)
    if w: D["acc"], D["_ctryAcc"] = w
    wb = run("wbProjects", wb_projects)
    if wb: D["wb"], D["_wbFossil"], D["_wbAcc"] = wb
    af = run("afdbIati", afdb_iati)
    if af: D["af"], D["_afFossil"], D["_afAcc"], D["gaps"] = af
    cw = run("climateWatch", climatewatch)
    if cw: D["ndc"] = cw
    am = run("afdbM300", afdb_m300)
    if am: D.setdefault("m300", {})["afdb"] = am
    wm = run("wbgM300", wbg_m300)
    if wm:
        old = D.setdefault("m300", {}).get("wbg", {})
        D["m300"]["wbg"] = {**old, **wm}
    # derived blocks
    fos = (D.get("_wbFossil") or []) + (D.get("_afFossil") or [])
    D["fossil"] = sorted(fos, key=lambda r: -r[4])[:12]
    D["accp"] = sorted((D.get("_wbAcc") or []) + (D.get("_afAcc") or []), key=lambda r: -r[4])[:10]
    comp = D.get("m300", {}).get("wbg", {}).get("compacts", {})
    rows = []
    ca = D.get("_ctryAcc", {}); wbc = D.get("wb", {}).get("ctry", {}); afc = D.get("af", {}).get("ctry", {}); nd = D.get("ndc", {})
    for i3, i2, nm, wbn in SSA:
        a = ca.get(i3, {}); n = nd.get(i3, {})
        rows.append(dict(iso=i3, name=nm, a15=a.get("a15"), a24=a.get("aL"), aY=a.get("aY"), c15=a.get("c15"), c24=a.get("cL"),
                         wb=wbc.get(nm, 0) or wbc.get(norm(wbn), 0), af=afc.get(i2, 0), ndc=n.get("ndc", ""), btr=n.get("btr", False), cn=n.get("cn"), cp=comp.get(nm, "")))
    D["rows"] = rows
    D["tiles"] = [[c, nd.get(c, {}).get("ndc", ""), nd.get(c, {}).get("btr", False)] for c in sorted(AF54)]
    meta["run"] = TODAY; meta["errors"] = errors
    D["meta"] = meta
    OUT.write_text(json.dumps(D, ensure_ascii=False, separators=(",", ":")))
    print("done; errors:", errors)

if __name__ == "__main__":
    main()
