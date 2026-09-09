import sqlite3
import sys
import json

DB_PATH = ".claude/code_graph.sqlite"

def query_graph(action, target):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    if action == "find_symbol":
        cur.execute("SELECT file_path, name, type, line FROM symbols WHERE name LIKE ?", (f"%{target}%",))
        rows = cur.fetchall()
        return [{"file": r[0], "symbol": r[1], "type": r[2], "line": r[3]} for r in rows]
        
    elif action == "get_callers":
        cur.execute("SELECT caller_file, caller_symbol FROM references_graph WHERE target_symbol = ?", (target,))
        rows = cur.fetchall()
        return [{"caller_file": r[0], "caller_symbol": r[1]} for r in rows]

    elif action == "get_callees":
        cur.execute("SELECT target_symbol FROM references_graph WHERE caller_symbol = ?", (target,))
        rows = cur.fetchall()
        return [{"calls": r[0]} for r in rows]
        
    conn.close()
    return []

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python graph_query.py <action: find_symbol|get_callers|get_callees> <target>")
        sys.exit(1)
        
    res = query_graph(sys.argv[1], sys.argv[2])
    print(json.dumps(res, indent=2))