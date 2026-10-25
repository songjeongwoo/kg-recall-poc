#!/usr/bin/env bash
# 모델 x 방식마다 프로세스 하나가 1~3회차를 차례로 돈다. 이미 끝난 질문은 건너뛰므로 중단 후 다시 실행해도 된다.
cd "$(dirname "$0")/.."
PY=${PY:-.venv/Scripts/python}
RUNS=${RUNS:-3}
for model in ${MODELS:-haiku sonnet opus fable}; do
  for method in ${METHODS:-graph_direct hybrid}; do
    (
      for run in $(seq 1 "$RUNS"); do
        "$PY" -X utf8 eval/run_eval.py --method "$method" --model "$model" --run "$run"
      done > "eval/results/run_${method}_${model}.log" 2>&1
    ) &
  done
done
wait
echo "all done"
