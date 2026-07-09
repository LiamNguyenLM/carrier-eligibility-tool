from dotenv import load_dotenv
import os
load_dotenv()
print("User password set:", bool(os.getenv("USER_PASSWORD")))
print("Admin password set:", bool(os.getenv("ADMIN_PASSWORD")))
