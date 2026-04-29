from resume_analyzer.chains.resume_chain import run_chain
def analyze_resume(parsed_resume: dict) -> dict:
    return run_chain(parsed_resume)