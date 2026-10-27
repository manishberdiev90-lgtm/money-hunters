"""Версионирование стратегий: новая версия активна только если улучшила чистую прибыль без роста ошибок."""
import json, time

def record(c, name, params, change, reason, stats):
    v = (c.execute("SELECT MAX(version) m FROM strategies WHERE name=?", (name,)).fetchone()["m"] or 0) + 1
    c.execute("""INSERT INTO strategies(name,version,params,change,reason,sample,tasks_ok,confirmed_usd,hours,expenses,errors,net,active,ts)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (name, v, json.dumps(params), change, reason, stats.get("sample", 0), stats.get("ok", 0), stats.get("confirmed", 0),
               stats.get("hours", 0), stats.get("expenses", 0), stats.get("errors", 0), stats.get("net", 0), 0, time.time()))
    c.commit()
    return v

def active(c, name):
    return c.execute("SELECT * FROM strategies WHERE name=? AND active=1", (name,)).fetchone()

def promote_if_better(c, name, version, min_sample=10):
    new = c.execute("SELECT * FROM strategies WHERE name=? AND version=?", (name, version)).fetchone()
    old = active(c, name)
    if new["sample"] < min_sample:
        return False, "мало данных для вывода"
    if old and not (new["net"] > old["net"] and new["errors"] <= old["errors"]):
        return False, "новая версия не лучше текущей"
    c.execute("UPDATE strategies SET active=0 WHERE name=?", (name,))
    c.execute("UPDATE strategies SET active=1 WHERE name=? AND version=?", (name, version))
    c.commit()
    return True, "версия принята"
