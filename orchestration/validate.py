"""Перевірка оркестрації: задачі, звіти воркерів і стан черги.

Запуск:
    python orchestration/validate.py            # перевірити все
    python orchestration/validate.py T04        # одну задачу і її звіт (якщо є)
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
TASK_SCHEMA = json.loads((ROOT / "task.schema.json").read_text())
RESULT_SCHEMA = json.loads((ROOT / "result.schema.json").read_text())
STATUSES = {"pending", "in_progress", "done", "failed", "skipped"}


def schema_errors(obj, schema):
    v = Draft202012Validator(schema)
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in v.iter_errors(obj)]


def check_task(task_id, state_ids):
    errors = []
    task_path = ROOT / "tasks" / f"{task_id}.json"
    if not task_path.exists():
        return [f"{task_id}: немає файлу {task_path.name}"]
    task = json.loads(task_path.read_text())
    errors += [f"{task_id} task: {e}" for e in schema_errors(task, TASK_SCHEMA)]
    if task.get("id") != task_id:
        errors.append(f"{task_id} task: id у файлі = {task.get('id')}")
    for dep in task.get("depends_on", []):
        if dep not in state_ids:
            errors.append(f"{task_id} task: залежність {dep} відсутня в черзі")

    result_path = ROOT / "results" / f"{task_id}.json"
    if result_path.exists():
        result = json.loads(result_path.read_text())
        errors += [f"{task_id} result: {e}" for e in schema_errors(result, RESULT_SCHEMA)]
        expected = {a["id"] for a in task.get("acceptance", [])}
        reported = {c["criterion_id"] for c in result.get("checks", [])}
        if missing := expected - reported:
            errors.append(f"{task_id} result: немає перевірок для {sorted(missing)}")
    return errors


def main(only=None):
    state = json.loads((ROOT / "state.json").read_text())
    queue = state["queue"]
    ids = [t["id"] for t in queue]
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("state: дубльовані id у черзі")
    by_id = {t["id"]: t for t in queue}
    for t in queue:
        if t["status"] not in STATUSES:
            errors.append(f"state {t['id']}: невідомий статус {t['status']}")
        if t["status"] == "done":
            if not (ROOT / "results" / f"{t['id']}.json").exists():
                errors.append(f"state {t['id']}: done, але немає звіту")
        if only and t["id"] != only:
            continue
        errors += check_task(t["id"], set(ids))
        if t["status"] in {"in_progress", "done"}:
            task = json.loads((ROOT / "tasks" / f"{t['id']}.json").read_text())
            for dep in task["depends_on"]:
                if by_id.get(dep, {}).get("status") not in {"done", "skipped"}:
                    errors.append(f"state {t['id']}: запущено до завершення {dep}")

    if errors:
        print("НЕ ПРОЙДЕНО:")
        print("\n".join(f"  - {e}" for e in errors))
        sys.exit(1)
    done = sum(t["status"] == "done" for t in queue)
    print(f"OK: {len(queue)} задач, виконано {done}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
