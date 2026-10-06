# Run-pack (step 2) — operator instructions, NOT yet executed

1. Rent RTX 4090 (RunPod community ~$0.35-0.5/h; keep volume for resume).
2. `bash runpod_setup.sh` (docker pulls BindCraft + Boltz-1 images,
   downloads ESM2/RFdiffusion weights ~6 GB).
3. `python jobrunner.py --target <pdb-or-uniprot> --n 1000 --out work/`
   resumable BindCraft generation; every design gets an attempt record.
4. `python jobrunner.py --screen work/ --top 400` Boltz-1 interface
   confidence on gate-passing designs (this is the ranker replay says we
   don't yet have — step 2's whole bet).
5. Submission export: gated + screened + diversity-constrained pick ->
   `submission.csv` + provenance manifest (sha256 per row).
6. Copy `work/` back locally; run `python -m bionexus.cli prove` after
   importing the run records (import path defined in step 2 code, TBD).

Honesty flag: until step 2 actually runs on hardware, all scripts here
are unverified intentions, not results.
