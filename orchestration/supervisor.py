"""Інструмент Supervisor'а: черга задач, промпти воркерів, журнал стану.

    python orchestration/supervisor.py ready                 # задачі, в яких виконані залежності
    python orchestration/supervisor.py start T04 "нотатки"   # пише промпт воркера у prompts/T04.md, статус in_progress
    python orchestration/supervisor.py finish T04 done "що перевірив сам"
    python orchestration/supervisor.py status
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"

PROMPT = """Ти воркер з роллю `{role}` у проєкті mykolaiv-drought. Задача {id}: {title}.

1. Прочитай `orchestration/WORKER.md` і дотримуйся його, зокрема правила «Точність чисел».
2. Прочитай свою задачу `orchestration/tasks/{id}.json`.
3. Прочитай звіти залежностей: {deps}.

Контекст від Supervisor'а:
{notes}

Виконай задачу, запиши звіт `orchestration/results/{id}.json` і перевір його командою
`python3 orchestration/validate.py {id}`.
"""


def load():
    return json.loads(STATE.read_text())


def save(state):
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def now():
    return datetime.now().isoformat(timespec="minutes")


def ready(state):
    done = {t["id"] for t in state["queue"] if t["status"] in {"done", "skipped"}}
    return [t for t in state["queue"] if t["status"] == "pending" and set(t["depends_on"]) <= done]


def main(cmd, *args):
    state = load()
    by_id = {t["id"]: t for t in state["queue"]}
    if cmd == "ready":
        for t in ready(state):
            print(f"{t['id']}  {t['day']}  {t['role']:<14} {t['title']}")
    elif cmd == "status":
        for t in state["queue"]:
            print(f"{t['id']}  {t['status']:<12} {t['title']}")
    elif cmd == "start":
        task_id, notes = args[0], (args[1] if len(args) > 1 else "немає")
        t = by_id[task_id]
        if t not in ready(state):
            sys.exit(f"{task_id} не готова до запуску")
        deps = ", ".join(f"`orchestration/results/{d}.json`" for d in t["depends_on"]) or "немає"
        text = PROMPT.format(role=t["role"], id=task_id, title=t["title"], deps=deps, notes=notes)
        (ROOT / "prompts" / f"{task_id}.md").write_text(text)
        t["status"], t["attempts"] = "in_progress", t["attempts"] + 1
        state["log"].append({"time": now(), "task": task_id, "event": f"start (спроба {t['attempts']})"})
        save(state)
        print(text)
    elif cmd == "finish":
        task_id, status, note = args[0], args[1], (args[2] if len(args) > 2 else "")
        by_id[task_id]["status"] = status
        state["log"].append({"time": now(), "task": task_id, "event": status, "supervisor_check": note})
        save(state)
        print(f"{task_id} -> {status}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(*sys.argv[1:])
