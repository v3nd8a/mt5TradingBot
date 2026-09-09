import os
import sqlite3
import ast

DB_PATH = ".claude/code_graph.sqlite"

def init_db():
    os.makedirs(".claude", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS symbols")
    cur.execute("DROP TABLE IF EXISTS references_graph")
    
    cur.execute("""
        CREATE TABLE symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT,
            name TEXT,
            type TEXT,
            line INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE references_graph (
            caller_file TEXT,
            caller_symbol TEXT,
            target_symbol TEXT
        )
    """)
    conn.commit()
    return conn

def parse_python_file(filepath, conn):
    cur = conn.cursor()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)
    except Exception:
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur.execute(
                "INSERT INTO symbols (file_path, name, type, line) VALUES (?, ?, ?, ?)",
                (filepath, node.name, "function", node.lineno)
            )
            # Фиксация вызовов внутри функции
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Call):
                    if isinstance(subnode.func, ast.Name):
                        cur.execute(
                            "INSERT INTO references_graph VALUES (?, ?, ?)",
                            (filepath, node.name, subnode.func.id)
                        )
        elif isinstance(node, ast.ClassDef):
            cur.execute(
                "INSERT INTO symbols (file_path, name, type, line) VALUES (?, ?, ?, ?)",
                (filepath, node.name, "class", node.lineno)
            )

def build_index():
    conn = init_db()
    for root, dirs, files in os.walk("."):
        # Игнорируем тяжелые директории
        dirs[:] = [d for d in dirs if d not in [".git", "node_modules", "__pycache__", ".venv", "dist", "build"]]
        for file in files:
            if file.endswith(".py"): # При необходимости расширяется под JS/TS/Go
                parse_python_file(os.path.join(root, file), conn)
    conn.commit()
    conn.close()
    print("Graph index built successfully in .claude/code_graph.sqlite")

if __name__ == "__main__":
    build_index()