# Train and run the model yourself

No training is started automatically. The 24 added cases are synthetic examples, not real
merchant records. They bring the available total to 285. The 79 test records stay unchanged.
More examples do not guarantee better results or 90% precision.

Run from PowerShell with the project's existing environment:

```powershell
Set-Location 'D:\Risky Rich\backend'
..\.venv\Scripts\python.exe training/train_synthetic_win_gate.py --supplement data/training_supplement.json --output eval/synthetic_win_gate_candidate.json --target-precision 0.90 --min-support 8
if ($LASTEXITCODE -ne 0) { throw 'Training failed. Keep the existing model.' }
..\.venv\Scripts\python.exe eval/evaluate_synthetic_gate.py --artifact eval/synthetic_win_gate_candidate.json
if ($LASTEXITCODE -ne 0) { throw 'Evaluation failed. Do not replace the existing model.' }
```

This trains the decision gate; it does not retrain the language model that reads evidence.
Review precision alongside recall, the number of decisions, and the number sent to a person.
Do not repeatedly tune the model against the same test results.

Only if you choose to use the candidate, back up and replace the current gate:

```powershell
$backupName = 'eval/synthetic_win_gate.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
Copy-Item -LiteralPath eval/synthetic_win_gate.json -Destination $backupName -ErrorAction Stop
Copy-Item -LiteralPath eval/synthetic_win_gate_candidate.json -Destination eval/synthetic_win_gate.json -ErrorAction Stop
Set-Location 'D:\Risky Rich'
docker compose up --build -d --wait --wait-timeout 900
```

Open http://localhost:8000. Rebuilding includes the updated gate in Docker. The UI's saved
headline figures are not automatically refreshed by candidate evaluation; do not present
them as the new model's results until they have been updated from a completed evaluation.

To run the existing model without training:

```powershell
Set-Location 'D:\Risky Rich'
docker compose build coconut
docker compose run --rm coconut python eval/prewarm_model.py
docker compose up -d --wait --wait-timeout 900 coconut
```
