"""
Доменный бенчмарк LLM для BI Analytics.
Прогоняет набор промптов через OpenAI-совместимый API (vLLM),
собирает latency и сохраняет ответы для ручной оценки.

Использование:
  python scripts/llm_bench_domain.py --model Qwen/Qwen3-8B --base-url http://localhost:8000/v1
"""
import argparse
import json
import time
import pathlib
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    raise SystemExit("pip install openai  # >= 1.0")

SYSTEM = (
    "Ты — помощник аналитика строительных проектов. "
    "Отвечай на русском, кратко и по делу."
)

PROMPTS = {
    # --- Общие (G) ---
    "G1": (
        "Перечисли 5 ключевых KPI строительного проекта. "
        "Ответ — нумерованным списком, без пояснений."
    ),
    "G2": (
        'Верни JSON-объект с полями "metric", "value", "unit" '
        "для следующей фразы: «Отклонение бюджета 12.5 млн руб.»"
    ),
    "G3": (
        "Бюджет плана 84 615 384.62 руб. Факт — 78 000 000 руб. "
        "Посчитай: абсолютное отклонение, процент отклонения. "
        "Ответ — Markdown-таблицей."
    ),
    "G4": (
        "Сократи текст до 2 предложений: "
        "«Проект Дмитровский-8 — жилой комплекс из 4 корпусов. "
        "Старт строительства: март 2023. Плановое завершение: декабрь 2025. "
        "Текущий статус: выполнено 72 %. Основное отклонение — задержка "
        "фундамента корпуса 3 на 45 дней из-за изменения грунтовых условий. "
        "Бюджет в пределах плана.»"
    ),
    "G5": (
        "У тебя нет доступа к базе данных. Ответь: какова точная дата "
        "завершения проекта «Сколково-7»? Если не знаешь — скажи, что данных нет."
    ),
    # --- Доменные (D) ---
    "D1": (
        "Задача «Фундамент сборный»: план завершения 10.01.2026, "
        "факт — 19.01.2026. Какое отклонение в днях? Критично ли это "
        "для проекта? Ответ в 3 предложениях."
    ),
    "D2": (
        "План бюджета раздела «КОРОБКА, КРОВЛЯ, СТЕНЫ»: 120 млн руб., "
        "факт: 134.2 млн руб. Рассчитай перерасход в % и предложи "
        "2 возможные причины."
    ),
    "D3": (
        "Задача «Идеальные полы» отклонилась на 28 дней. "
        "Раздел — «КОРОБКА, КРОВЛЯ, СТЕНЫ». Сформулируй 3 вероятные "
        "причины отклонения для строительного контекста."
    ),
    "D4": (
        "Объясни, что означают колонки «РД по Договору», "
        "«Отклонение разделов РД», «Всего загружено», «На согласовании» "
        "в контексте строительного проекта. Ответ — 4 пункта."
    ),
    "D5": (
        "Проект стартовал 01.03.2023, плановый конец — 30.12.2025. "
        "Выполнено 72 %. Текущее отклонение +45 дней. "
        "Оцени прогнозную дату завершения. Покажи расчёт."
    ),
    "D6": (
        "Дана таблица:\n"
        "| Проект | Бюджет План | Бюджет Факт |\n"
        "|---|---|---|\n"
        "| Альфа | 100 | 95 |\n"
        "| Бета | 200 | 230 |\n"
        "| Гамма | 150 | 150 |\n\n"
        "Какой проект в зоне риска? Ответ — 1 предложение."
    ),
    "D7": (
        "Контрагент «Строй-М» за 3 неделю отработал 120 чел.-дней "
        "при плане 95. Дельта +26 %. Это хорошо или плохо? "
        "Объясни в контексте ресурсного контроля."
    ),
    "D8": (
        "Этап «Кабелетоковые каналы»: отклонение 0 дней. "
        "Этап «Металлические конструкции»: +18 дней. "
        "Составь короткий аналитический вывод для руководителя."
    ),
    "D9": (
        "Сформируй Markdown-таблицу «Топ-3 задачи по отклонению» "
        "с колонками: Задача, Отклонение (дни), Причина — на основе "
        "данных: Фундамент +9, Полы +28 (нет подрядчика), Кровля +3."
    ),
    "D10": (
        "Отклонение 0 дней — зелёный, 1–14 дней — жёлтый, "
        ">14 дней — красный. Задача с отклонением 18 дней — "
        "какой статус? Ответ одним словом + цвет."
    ),
    "D11": (
        "Напиши 1 абзац (3–4 предложения) для слайда "
        "«Статус проекта Дмитровский-8» на основе: выполнено 72 %, "
        "бюджет в плане, срок сдвинут на 45 дней, причина — грунт."
    ),
    "D12": (
        "Пользователь спрашивает: «Покажи все задачи проекта Есенина-V "
        "с отклонением больше 10 дней». Сформулируй SQL-запрос к таблице "
        "tasks(project_name, task_name, deviation_days)."
    ),
    "D13": (
        "На столбчатом графике «План/факт по этапам» красный столбец "
        "(факт) выходит правее синего (план) на 2 см. Что это означает "
        "для менеджера проекта? Ответ — 2 предложения."
    ),
    "D14": (
        "Проект: 3 задачи в красной зоне (>14 дней), 5 в жёлтой, "
        "12 в зелёной. Предложи 3 конкретных управленческих действия."
    ),
    "D15": (
        "Переведи на английский: «Отклонение фактических сроков от "
        "базового плана по проекту составляет 45 календарных дней. "
        "Основная причина — изменение проектных решений по фундаменту.»"
    ),
}

RUNS = 3
PAUSE_BETWEEN_RUNS_S = 5


def run_bench(client: OpenAI, model: str, out_dir: pathlib.Path):
    results = []
    total = len(PROMPTS) * RUNS
    done = 0

    for prompt_id, prompt_text in PROMPTS.items():
        for run in range(1, RUNS + 1):
            done += 1
            t0 = time.perf_counter()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": prompt_text},
                    ],
                    temperature=0.3,
                    top_p=0.9,
                    max_tokens=512,
                )
                elapsed = time.perf_counter() - t0
                content = resp.choices[0].message.content or ""
                tok_out = (
                    resp.usage.completion_tokens
                    if resp.usage
                    else len(content.split())
                )
                tok_in = resp.usage.prompt_tokens if resp.usage else 0
                error = None
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                content = ""
                tok_out = 0
                tok_in = 0
                error = str(exc)

            tok_s = round(tok_out / elapsed, 1) if elapsed > 0 and tok_out else 0
            results.append(
                {
                    "prompt_id": prompt_id,
                    "run": run,
                    "model": model,
                    "input_tokens": tok_in,
                    "output_tokens": tok_out,
                    "elapsed_s": round(elapsed, 3),
                    "tok_per_sec": tok_s,
                    "answer": content,
                    "error": error,
                    "quality_score": None,
                }
            )
            status = f"[{done}/{total}]"
            if error:
                print(f"  {status} {prompt_id} run={run}  ERROR: {error[:80]}")
            else:
                print(
                    f"  {status} {prompt_id} run={run}  "
                    f"{tok_out} tok  {elapsed:.2f}s  {tok_s} tok/s"
                )
            time.sleep(PAUSE_BETWEEN_RUNS_S)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = model.replace("/", "_")
    out_file = out_dir / f"bench_{safe_model}_{ts}.json"
    out_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nРезультаты сохранены → {out_file}")

    ok = [r for r in results if r["error"] is None]
    if ok:
        avg_tok_s = sum(r["tok_per_sec"] for r in ok) / len(ok)
        avg_elapsed = sum(r["elapsed_s"] for r in ok) / len(ok)
        print(f"Средний tok/s: {avg_tok_s:.1f}  |  Средняя latency: {avg_elapsed:.2f}s")
    print("Заполните 'quality_score' (1–5) вручную в JSON-файле для итоговой сводки.")
    return results


def main():
    ap = argparse.ArgumentParser(
        description="LLM domain benchmark for BI Analytics"
    )
    ap.add_argument("--model", required=True, help="Model name (as in vLLM)")
    ap.add_argument(
        "--base-url",
        default="http://localhost:8000/v1",
        help="vLLM OpenAI-compatible base URL",
    )
    ap.add_argument(
        "--out-dir",
        default="docs/bench_results",
        help="Directory for result JSON files",
    )
    ap.add_argument(
        "--runs",
        type=int,
        default=RUNS,
        help=f"Number of runs per prompt (default {RUNS})",
    )
    args = ap.parse_args()

    global RUNS, PAUSE_BETWEEN_RUNS_S
    RUNS = args.runs

    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = OpenAI(base_url=args.base_url, api_key="not-needed")
    print(f"=== Benchmark: {args.model} ({RUNS} runs x {len(PROMPTS)} prompts) ===\n")
    run_bench(client, args.model, out_dir)


if __name__ == "__main__":
    main()
