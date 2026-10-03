.PHONY: install test sim report ablate bench api ui
install: ; pip install -r requirements-dev.txt -r requirements-ml.txt
test: ; python -m pytest -v
sim: ; python -m sdms.simulator --drops 200
report: ; python -m sdms.eval.report
ablate: ; python scripts/ablation.py
bench: ; python scripts/benchmark_latency.py
api: ; uvicorn sdms.api.main:create_app --factory --port 8000 --reload
ui: ; streamlit run sdms/ui/app.py
