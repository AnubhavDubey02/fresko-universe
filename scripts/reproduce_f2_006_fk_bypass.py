"""Isolated MariaDB 10.6 reproduction of the former independent FK bypass.

Uses only the disposable fresko-f2-mariadb container, not an application site.
The three InnoDB tables deliberately include real foreign keys; the pinned
Frappe tests separately verify the behavior on actual DocType tables.
"""
import subprocess

COMMAND = ["docker", "exec", "-i", "fresko-f2-mariadb", "mariadb",
           "-uroot", "-pfresko-local-test-only", "-N", "--unbuffered"]


def sql(statement):
    return subprocess.check_output(COMMAND, input=statement, text=True)


print(sql("""
CREATE DATABASE IF NOT EXISTS f2_006_probe;
USE f2_006_probe;
CREATE TABLE IF NOT EXISTS evidence (name VARCHAR(140) PRIMARY KEY) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS attachment (
 name VARCHAR(140) PRIMARY KEY, evidence VARCHAR(140),
 FOREIGN KEY (evidence) REFERENCES evidence(name)) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS attempt (
 name VARCHAR(140) PRIMARY KEY, evidence VARCHAR(140), attachment VARCHAR(140),
 FOREIGN KEY (evidence) REFERENCES evidence(name),
 FOREIGN KEY (attachment) REFERENCES attachment(name)) ENGINE=InnoDB;
SELECT VERSION();
"""))
import uuid
key = uuid.uuid4().hex
caller = subprocess.Popen(COMMAND, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          text=True)
try:
    caller.stdin.write(f"USE f2_006_probe; START TRANSACTION; INSERT INTO evidence VALUES ('{key}'); "
                       f"INSERT INTO attachment VALUES ('{key}', '{key}'); SELECT 'caller_uncommitted';\n")
    caller.stdin.flush()
    assert caller.stdout.readline().strip() == "caller_uncommitted"
    sql(f"USE f2_006_probe; SET foreign_key_checks=0; "
        f"INSERT INTO attempt VALUES ('{key}', '{key}', '{key}');")
    caller.stdin.write("ROLLBACK; SELECT 'caller_rolled_back';\n")
    caller.stdin.flush()
    assert caller.stdout.readline().strip() == "caller_rolled_back"
    counts = sql(f"""USE f2_006_probe;
      SELECT COUNT(*), SUM(e.name IS NULL), SUM(a.name IS NULL)
      FROM attempt t LEFT JOIN evidence e ON e.name=t.evidence
      LEFT JOIN attachment a ON a.name=t.attachment WHERE t.name='{key}';""").strip()
    assert counts == "1\t1\t1", counts
    print("persisted_attempts=1 missing_evidence=1 missing_attachment=1 after_caller_rollback")
finally:
    caller.stdin.close()
    caller.wait(timeout=10)
