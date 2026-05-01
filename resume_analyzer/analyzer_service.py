from resume_analyzer.chains.resume_chain import run_chain
async def analyze_resume(parsed_resume: dict) -> dict:
    return  await run_chain(parsed_resume)