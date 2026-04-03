# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database.db import create_tables
from routers import auth, gmail, outlook
from routers.employee_auth import router as employee_router  
from models.employee import Employee                         


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
app.include_router(gmail.router)
app.include_router(outlook.router)
app.include_router(employee_router)                      


@app.get("/")
def root():
    return {
        "message": "Email Parser API is running ",
        "docs":    "http://localhost:8000/docs"
    }