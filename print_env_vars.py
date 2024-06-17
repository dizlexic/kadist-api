import os

from dotenv import dotenv_values

if __name__ == "__main__":
    config = dotenv_values(".env")
    env_vars = os.environ.copy()
    for key, value in config.items():
        print(f"{key}={value}")

