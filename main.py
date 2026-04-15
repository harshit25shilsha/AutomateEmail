# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database.db import create_tables
from routers import auth
from routers.email_routers import router as email_routers
from routers.employee_auth import router as employee_router  
from models.employee import Employee  
from routers.resume_router import router as resume_router



app = FastAPI(
    title       = "Email Parser API",
    description = "Hiring automation — Gmail & Outlook inbox parser",
    version     = "1.0.0"
)

# CORS for frontend dev
app.add_middleware(
    CORSMiddleware,
    #allow_origins     = ["*"],
    allow_origins     = ["*","http://localhost:3000"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

@app.on_event("startup")
def startup():
    create_tables()
    print(" Database tables created")

app.include_router(auth.router)
app.include_router(email_routers)
app.include_router(employee_router)  
app.include_router(resume_router)                    


@app.get("/")
def root():
    return {
        "message": "Email Parser API is running ",
        "docs":    "http://localhost:8000/docs"
    }