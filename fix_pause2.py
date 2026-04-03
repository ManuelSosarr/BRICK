path = r'app\routes_agent.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

old_resume = "cur.execute(\n                \"UPDATE vicidial_live_agents SET external_pause = 'RESUME' WHERE user = %s\",\n                (vici_user,)\n            )\n            conn.commit()\n            affected = cur.rowcount"
new_resume = "cur.execute(\n                \"UPDATE vicidial_live_agents SET external_pause = 'RESUME' WHERE user = %s\",\n                (vici_user,)\n            )\n            conn.commit()\n            affected = cur.rowcount\n            import time; time.sleep(2)\n            cur.execute(\"UPDATE vicidial_live_agents SET external_pause = '' WHERE user = %s\", (vici_user,))\n            conn.commit()"

old_pause = "cur.execute(\n                \"UPDATE vicidial_live_agents SET external_pause = 'PAUSE' WHERE user = %s\",\n                (vici_user,)\n            )\n            conn.commit()\n            affected = cur.rowcount"
new_pause = "cur.execute(\n                \"UPDATE vicidial_live_agents SET external_pause = 'PAUSE' WHERE user = %s\",\n                (vici_user,)\n            )\n            conn.commit()\n            affected = cur.rowcount\n            import time; time.sleep(2)\n            cur.execute(\"UPDATE vicidial_live_agents SET external_pause = '' WHERE user = %s\", (vici_user,))\n            conn.commit()"

content = content.replace(old_resume, new_resume)
content = content.replace(old_pause, new_pause)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('time.sleep' in open(path).read())
