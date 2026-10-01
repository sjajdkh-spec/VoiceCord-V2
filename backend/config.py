import json
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("config")

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")

TOKENS_FILE = BASE_DIR / "tokens.json"
BOT_CONFIG_FILE = BASE_DIR / "bot_config.json"

# MongoDB connection optional initialization
mongo_client = None
db = None

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()

if MONGODB_URI:
    try:
        import pymongo
        mongo_client = pymongo.MongoClient(MONGODB_URI, serverSelectionTimeoutMS=4000)
        # Verify connection
        mongo_client.admin.command('ping')
        try:
            db = mongo_client.get_database()
        except Exception:
            db = mongo_client.get_database("voicecord")
        logger.info("Successfully connected to MongoDB.")
    except Exception as e:
        logger.warning(f"MongoDB connection failed: {e}. Falling back to local storage only.")
        mongo_client = None
        db = None


def load_config():
    """Load admin user & password from environment variables (.env)."""
    admin_user = os.getenv("ADMIN_USER", "root").strip()
    admin_pass = os.getenv("ADMIN_PASS", "@subhan1515").strip()
    mongodb_uri = os.getenv("MONGODB_URI", "").strip()
    return {
        "admin_user": admin_user,
        "admin_pass": admin_pass,
        "mongodb_uri": mongodb_uri,
        "mongo_connected": db is not None
    }


def load_tokens() -> dict:
    """
    Loads tokens from local file and MongoDB (if available).
    Dual-sync behavior: Syncs MongoDB data into local storage and vice-versa.
    """
    tokens = {}
    
    # 1. Load local file
    if TOKENS_FILE.exists():
        try:
            with open(TOKENS_FILE, "r", encoding="utf-8") as f:
                tokens = json.load(f)
        except Exception as e:
            logger.error(f"Error loading local tokens.json: {e}")

    # 2. Load / sync from MongoDB if connected
    if db is not None:
        try:
            mongo_tokens = {}
            cursor = db.tokens.find({}, {"_id": 0})
            for item in cursor:
                t_str = item.get("token")
                if t_str:
                    # remove token field from dict body
                    cfg = {k: v for k, v in item.items() if k != "token"}
                    mongo_tokens[t_str] = cfg
            
            # Merge Mongo tokens with Local tokens
            for t_str, cfg in mongo_tokens.items():
                if t_str not in tokens:
                    tokens[t_str] = cfg

            # Also ensure local file reflects merged data
            save_tokens_local(tokens)
        except Exception as e:
            logger.error(f"Error fetching tokens from MongoDB: {e}")

    return tokens


def save_tokens_local(data: dict):
    """Saves tokens dict to local JSON file."""
    try:
        with open(TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving tokens to local file: {e}")


def save_tokens(data: dict):
    """
    Dual Storage Save:
    Saves to both local tokens.json file AND MongoDB (if connected).
    """
    # 1. Save to local
    save_tokens_local(data)

    # 2. Save to MongoDB
    if db is not None:
        try:
            db.tokens.delete_many({})
            if data:
                docs = []
                for token_str, cfg in data.items():
                    doc = {"token": token_str}
                    doc.update(cfg)
                    docs.append(doc)
                db.tokens.insert_many(docs)
            logger.info("Tokens successfully saved/synced to MongoDB.")
        except Exception as e:
            logger.error(f"Error saving tokens to MongoDB: {e}")


def load_bot_config() -> dict:
    """Loads Bot configuration (token, bot_id, bot_secret, active)."""
    cfg = {"bot_token": "", "bot_id": "", "bot_secret": "", "active": False}
    
    if BOT_CONFIG_FILE.exists():
        try:
            with open(BOT_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:
            pass

    if db is not None:
        try:
            mongo_cfg = db.bot_config.find_one({"_id": "main_bot"}, {"_id": 0})
            if mongo_cfg:
                cfg.update(mongo_cfg)
        except Exception as e:
            logger.error(f"Error reading bot_config from MongoDB: {e}")

    return cfg


def save_bot_config(cfg: dict):
    """Dual Storage save for Bot configuration."""
    try:
        with open(BOT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving bot_config to local file: {e}")

    if db is not None:
        try:
            db.bot_config.replace_one({"_id": "main_bot"}, cfg, upsert=True)
            logger.info("Bot config successfully saved to MongoDB.")
        except Exception as e:
            logger.error(f"Error saving bot_config to MongoDB: {e}")
