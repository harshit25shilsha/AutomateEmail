from google_auth_oauthlib.flow import InstalledAppFlow
import json
 
SCOPES = ["https://www.googleapis.com/auth/drive"]
 
flow = InstalledAppFlow.from_client_secrets_file("oauth_credentials.json", SCOPES)
creds = flow.run_local_server(port=0)
 
# Save token
with open("token.json", "w") as f:
    f.write(creds.to_json())
 
print("✓ token.json saved. You can now run your server.")