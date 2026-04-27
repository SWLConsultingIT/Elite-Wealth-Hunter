import httpx
import time
import random
import logging
import os
import uuid
from flask import Flask, request, jsonify
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

IG_APP_ID = "936619743392459"


def get_session():
    return {
        "sessionid": os.environ.get("IG_SESSION_ID", ""),
        "ds_user_id": os.environ.get("IG_DS_USER_ID", ""),
        "csrftoken": os.environ.get("IG_CSRF_TOKEN", ""),
        "ig_did": os.environ.get("IG_DID", str(uuid.uuid4()).upper()),
    }


def make_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "x-ig-app-id": IG_APP_ID,
        "x-csrftoken": os.environ.get("IG_CSRF_TOKEN", ""),
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
    }


def safe_delay(min_s=2, max_s=5):
    time.sleep(random.uniform(min_s, max_s))


def fetch_hashtag_sections(hashtag: str, max_id: str = None):
    headers = {**make_headers(), "Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "tab": "recent",
        "page": 1,
        "surface": "explore_media_grid",
        "include_persistent": "true",
    }
    if max_id:
        data["max_id"] = max_id

    url = f"https://www.instagram.com/api/v1/tags/{hashtag}/sections/"

    with httpx.Client(headers=headers, cookies=get_session(), timeout=30, follow_redirects=True) as client:
        resp = client.post(url, data=data)
        resp.raise_for_status()
        return resp.json()


def fetch_user_info(user_id: str):
    url = f"https://i.instagram.com/api/v1/users/{user_id}/info/"
    with httpx.Client(headers=make_headers(), cookies=get_session(), timeout=30, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code == 200:
            return resp.json().get("user", {})
    return None


def extract_posts(sections_data):
    posts = []
    for section in sections_data.get("sections", []):
        for item in section.get("layout_content", {}).get("medias", []):
            media = item.get("media", {})
            if media:
                posts.append(media)
    return posts


def build_profile(user_data: dict, source_hashtag: str = "") -> dict:
    return {
        "username": user_data.get("username", ""),
        "fullName": user_data.get("full_name", ""),
        "biography": user_data.get("biography", ""),
        "followersCount": user_data.get("follower_count", 0),
        "followingCount": user_data.get("following_count", 0),
        "postsCount": user_data.get("media_count", 0),
        "isVerified": user_data.get("is_verified", False),
        "isPrivate": user_data.get("is_private", False),
        "isBusinessAccount": user_data.get("is_business", False),
        "profilePicture": user_data.get("profile_pic_url", ""),
        "externalUrl": user_data.get("external_url", "") or "",
        "category": user_data.get("category", "") or "",
        "scrapedAt": int(time.time()),
        "sourceHashtag": source_hashtag,
    }


def build_profile_from_post_user(user_basic: dict, source_hashtag: str = "") -> dict:
    return {
        "username": user_basic.get("username", ""),
        "fullName": user_basic.get("full_name", ""),
        "biography": "",
        "followersCount": 0,
        "followingCount": 0,
        "postsCount": 0,
        "isVerified": user_basic.get("is_verified", False),
        "isPrivate": user_basic.get("is_private", False),
        "isBusinessAccount": False,
        "profilePicture": user_basic.get("profile_pic_url", ""),
        "externalUrl": "",
        "category": "",
        "scrapedAt": int(time.time()),
        "sourceHashtag": source_hashtag,
    }


def scrape_hashtag_internal(hashtag: str, limit: int, seen_usernames: set) -> list:
    profiles = []
    max_id = None
    errors = 0

    while len(profiles) < limit:
        try:
            result = fetch_hashtag_sections(hashtag, max_id)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                logger.warning("Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if status in (401, 403):
                logger.error("Session expired or invalid")
                break
            errors += 1
            if errors > 3:
                break
            safe_delay(5, 10)
            continue
        except Exception as e:
            logger.error(f"Request error: {e}")
            errors += 1
            if errors > 3:
                break
            continue

        posts = extract_posts(result)
        if not posts:
            break

        for post in posts:
            if len(profiles) >= limit:
                break

            user_basic = post.get("user", {})
            username = user_basic.get("username", "")
            user_id = str(user_basic.get("pk", ""))

            if not username or username in seen_usernames:
                continue
            if user_basic.get("is_private"):
                continue

            seen_usernames.add(username)

            safe_delay()
            user_data = fetch_user_info(user_id)

            profile = (
                build_profile(user_data, hashtag)
                if user_data
                else build_profile_from_post_user(user_basic, hashtag)
            )
            profiles.append(profile)
            logger.info(f"✓ {len(profiles)}/{limit}: @{username}")

        if not result.get("more_available") or not result.get("next_max_id"):
            break
        max_id = result["next_max_id"]
        safe_delay(3, 6)

    return profiles


@app.route("/", methods=["GET"])
def health_check():
    session_ok = bool(os.environ.get("IG_SESSION_ID"))
    return jsonify({
        "status": "Instagram GraphQL Scraper",
        "version": "2.0",
        "session_configured": session_ok,
        "endpoints": ["/scrape_hashtag", "/scrape_multiple"],
    })


@app.route("/scrape_hashtag", methods=["POST"])
def scrape_hashtag():
    try:
        data = request.json or {}
        hashtag = data.get("hashtag", "yachtlife").replace("#", "")
        limit = min(int(data.get("limit", 50)), 100)

        if not os.environ.get("IG_SESSION_ID"):
            return jsonify({"success": False, "error": "IG_SESSION_ID env var not set"}), 500

        logger.info(f"Scraping #{hashtag}, limit: {limit}")
        profiles = scrape_hashtag_internal(hashtag, limit, set())

        return jsonify({
            "success": True,
            "hashtag": hashtag,
            "profiles_found": len(profiles),
            "profiles": profiles,
            "timestamp": int(time.time()),
        })

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"success": False, "error": str(e), "profiles": []}), 500


@app.route("/scrape_multiple", methods=["POST"])
def scrape_multiple():
    try:
        data = request.json or {}
        hashtags = data.get("hashtags", ["yachtlife"])
        limit_per = min(int(data.get("limit_per_hashtag", 20)), 30)

        if not os.environ.get("IG_SESSION_ID"):
            return jsonify({"success": False, "error": "IG_SESSION_ID env var not set"}), 500

        all_profiles = []
        seen = set()

        for hashtag in hashtags:
            hashtag = hashtag.replace("#", "")
            logger.info(f"Scraping #{hashtag}")
            profiles = scrape_hashtag_internal(hashtag, limit_per, seen)
            all_profiles.extend(profiles)
            for p in profiles:
                seen.add(p["username"])
            time.sleep(random.uniform(5, 10))

        return jsonify({
            "success": True,
            "hashtags_scraped": hashtags,
            "total_profiles": len(all_profiles),
            "profiles": all_profiles,
            "timestamp": int(time.time()),
        })

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"success": False, "error": str(e), "profiles": []}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
