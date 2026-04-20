import instaloader
import json
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import random
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize instaloader with optimal settings
L = instaloader.Instaloader(
    download_videos=False,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False,
    post_metadata_txt_pattern='',
    storyitem_metadata_txt_pattern=''
)

def safe_delay():
    """Random delay to avoid rate limits"""
    delay = random.uniform(2, 5)
    time.sleep(delay)

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        "status": "Free Instagram Scraper API",
        "version": "1.0",
        "endpoints": ["/scrape_hashtag", "/scrape_multiple"],
        "author": "Elite Wealth Hunter"
    })

@app.route('/scrape_hashtag', methods=['POST'])
def scrape_hashtag():
    try:
        data = request.json or {}
        hashtag = data.get('hashtag', 'yachtlife').replace('#', '')
        limit = min(int(data.get('limit', 50)), 100)  # Max 100 for safety
        
        logger.info(f"Starting scrape: #{hashtag}, limit: {limit}")
        
        profiles = []
        seen_usernames = set()
        errors = 0
        
        try:
            hashtag_obj = instaloader.Hashtag.from_name(L.context, hashtag)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Hashtag not found: {hashtag}',
                'profiles': []
            }), 404
        
        for i, post in enumerate(hashtag_obj.get_posts()):
            if len(profiles) >= limit:
                break
                
            if i >= limit * 2:  # Safety break
                break
            
            try:
                username = post.owner_username
                
                # Skip duplicates
                if username in seen_usernames:
                    continue
                    
                seen_usernames.add(username)
                
                # Get profile details
                profile = post.owner_profile
                
                # Skip private profiles for better data quality
                if profile.is_private:
                    continue
                
                # Get recent posts (limit 3 for efficiency)
                recent_posts = []
                try:
                    post_count = 0
                    for recent_post in profile.get_posts():
                        if post_count >= 3:
                            break
                        recent_posts.append({
                            'shortcode': recent_post.shortcode,
                            'caption': recent_post.caption[:300] if recent_post.caption else '',
                            'likesCount': recent_post.likes,
                            'commentsCount': recent_post.comments,
                            'displayUrl': recent_post.url,
                            'timestamp': recent_post.date.isoformat(),
                            'locationName': recent_post.location.name if recent_post.location else ''
                        })
                        post_count += 1
                except:
                    pass  # If can't get posts, continue with profile
                
                # Build profile object
                profile_data = {
                    'username': username,
                    'fullName': profile.full_name or '',
                    'biography': profile.biography or '',
                    'followersCount': profile.followers,
                    'followingCount': profile.followees,
                    'postsCount': profile.mediacount,
                    'isVerified': profile.is_verified,
                    'isPrivate': profile.is_private,
                    'isBusinessAccount': profile.is_business_account,
                    'profilePicture': profile.profile_pic_url,
                    'externalUrl': profile.external_url or '',
                    'latestPosts': recent_posts,
                    'location': '',
                    'scrapedAt': int(time.time()),
                    'sourceHashtag': hashtag
                }
                
                profiles.append(profile_data)
                logger.info(f"✓ Scraped {len(profiles)}/{limit}: @{username}")
                
                # Rate limiting
                safe_delay()
                
            except Exception as e:
                errors += 1
                logger.warning(f"Error with post {i}: {str(e)}")
                if errors > 10:  # Too many errors, stop
                    break
                continue
        
        result = {
            'success': True,
            'hashtag': hashtag,
            'requested_limit': limit,
            'profiles_found': len(profiles),
            'profiles': profiles,
            'timestamp': int(time.time()),
            'errors_encountered': errors
        }
        
        logger.info(f"✅ Completed: {len(profiles)} profiles scraped from #{hashtag}")
        return jsonify(result)
        
    except Exception as e:
        error_msg = f"Scraping error: {str(e)}"
        logger.error(error_msg)
        return jsonify({
            'success': False,
            'error': error_msg,
            'profiles': []
        }), 500

@app.route('/scrape_multiple', methods=['POST'])
def scrape_multiple_hashtags():
    """Scrape multiple hashtags in one call"""
    try:
        data = request.json or {}
        hashtags = data.get('hashtags', ['yachtlife'])
        limit_per_hashtag = min(int(data.get('limit_per_hashtag', 20)), 30)
        
        all_profiles = []
        seen_usernames = set()
        
        for hashtag in hashtags:
            logger.info(f"Scraping #{hashtag}")
            
            # Internal call to single hashtag scraper
            hashtag_profiles = scrape_single_hashtag(hashtag, limit_per_hashtag, seen_usernames)
            all_profiles.extend(hashtag_profiles)
            
            # Update seen usernames
            for profile in hashtag_profiles:
                seen_usernames.add(profile['username'])
            
            # Delay between hashtags
            time.sleep(random.uniform(3, 6))
        
        return jsonify({
            'success': True,
            'hashtags_scraped': hashtags,
            'total_profiles': len(all_profiles),
            'profiles': all_profiles,
            'timestamp': int(time.time())
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'profiles': []
        }), 500

def scrape_single_hashtag(hashtag, limit, seen_usernames):
    """Helper function for single hashtag scraping"""
    profiles = []
    hashtag = hashtag.replace('#', '')
    
    try:
        hashtag_obj = instaloader.Hashtag.from_name(L.context, hashtag)
        
        for i, post in enumerate(hashtag_obj.get_posts()):
            if len(profiles) >= limit or i >= limit * 2:
                break
                
            username = post.owner_username
            if username in seen_usernames:
                continue
                
            try:
                profile = post.owner_profile
                if profile.is_private:
                    continue
                
                profile_data = {
                    'username': username,
                    'fullName': profile.full_name or '',
                    'biography': profile.biography or '',
                    'followersCount': profile.followers,
                    'followingCount': profile.followees,
                    'isVerified': profile.is_verified,
                    'sourceHashtag': hashtag
                }
                
                profiles.append(profile_data)
                safe_delay()
                
            except:
                continue
                
    except Exception as e:
        logger.error(f"Error scraping #{hashtag}: {str(e)}")
    
    return profiles

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)