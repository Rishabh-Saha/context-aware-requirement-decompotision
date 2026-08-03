"""Read-only profile of every table and column in a SEOSS SQLite db.
For each column: fill rate, distinct count, and a few example values (truncated).
For low-cardinality columns, shows the full value distribution (great for finding
things like the exact `type`, `status`, `resolution`, `priority` vocabularies)."""
import sqlite3, sys, textwrap

db = sys.argv[1] if len(sys.argv) > 1 else "data/seoss33/pig.sqlite"
con = sqlite3.connect(db); con.row_factory = sqlite3.Row
cur = con.cursor()

tables = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

def short(v, n=70):
    if v is None: return "NULL"
    s = " ".join(str(v).split())
    return s[:n] + ("…" if len(s) > n else "")

for t in tables:
    total = cur.execute(f"SELECT COUNT(*) FROM '{t}'").fetchone()[0]
    print("\n" + "=" * 78)
    print(f"TABLE {t}  —  {total} rows")
    print("=" * 78)
    cols = [r["name"] for r in cur.execute(f"PRAGMA table_info('{t}')")]
    for c in cols:
        nonnull = cur.execute(
            f"SELECT COUNT(*) FROM '{t}' WHERE \"{c}\" IS NOT NULL AND \"{c}\"!=''").fetchone()[0]
        distinct = cur.execute(
            f"SELECT COUNT(DISTINCT \"{c}\") FROM '{t}'").fetchone()[0]
        fill = f"{(nonnull/total*100):.0f}%" if total else "n/a"
        print(f"\n  {c}: {fill} filled, {distinct} distinct")
        if 0 < distinct <= 15:
            for r in cur.execute(
                f"SELECT \"{c}\" v, COUNT(*) n FROM '{t}' "
                f"WHERE \"{c}\" IS NOT NULL AND \"{c}\"!='' "
                f"GROUP BY \"{c}\" ORDER BY n DESC"):
                print(f"      {r['n']:>6}  {short(r['v'])}")
        else:
            for r in cur.execute(
                f"SELECT \"{c}\" v FROM '{t}' "
                f"WHERE \"{c}\" IS NOT NULL AND \"{c}\"!='' LIMIT 3"):
                print(f"      e.g.  {short(r['v'])}")
con.close()