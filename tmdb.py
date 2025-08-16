import io
import os
import json
import re
import requests
import time


# TMDb API constants
TMDB_API_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/"
POSTER_SIZE = "w342"  # Medium size poster
BACKDROP_SIZE = "w780"  # Medium size backdrop

# Cache settings
CACHE_EXPIRY = 7 * 24 * 60 * 60  # 7 days in seconds
MAX_CACHE_ENTRIES = 1000

class TMDbAPI:
    """TMDb API wrapper for YAWSP"""
    
    def __init__(self, addon, profile_path):
        self.addon = addon
        self.api_key = addon.getSetting('tmdb_apikey')
        self.language = addon.getSetting('tmdb_language') or 'en-US'
        self.include_adult = addon.getSetting('tmdb_adult') == 'true'
        self.profile_path = profile_path
        self.cache_file = os.path.join(profile_path, 'tmdb_cache.json')
        self.cache = self._load_cache()

    def enhance_search_query(self, user_query):
        """
        Enhance user search query by finding the most likely movie/show match
        and returning optimized search terms for Webshare
        """
        if not self.api_key:
            return [user_query]  # Fallback to original query
        
        # Try to search for movies first
        movie_result = self.search_movie(user_query)
        
        search_variants = [user_query]  # Always include original query
        
        if movie_result:
            # Add official title variants
            if movie_result.get('title') and movie_result['title'].lower() != user_query.lower():
                search_variants.append(movie_result['title'])
            
            # Add original title if different
            if movie_result.get('original_title') and movie_result['original_title'].lower() != user_query.lower():
                search_variants.append(movie_result['original_title'])
            
            # Add title with year
            if movie_result.get('release_date'):
                year = movie_result['release_date'][:4]
                search_variants.append(f"{movie_result['title']} {year}")
                
            # Add alternative formats
            title = movie_result['title']
            search_variants.extend([
                title.upper(),  # All caps version
                title.replace(' ', '.'),  # Dot separated
                title.replace(' ', '_'),  # Underscore separated
            ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for variant in search_variants:
            if variant.lower() not in seen:
                seen.add(variant.lower())
                unique_variants.append(variant)
        
        return unique_variants
        
    def _load_cache(self):
        """Load the TMDb cache from disk"""
        try:
            if os.path.exists(self.cache_file):
                with io.open(self.cache_file, 'r', encoding='utf8') as f:
                    cache_data = json.load(f)
                # Clean expired entries
                now = time.time()
                cache_data = {k: v for k, v in cache_data.items() 
                              if v.get('timestamp', 0) + CACHE_EXPIRY > now}
                return cache_data
        except Exception as e:
            print(f"Error loading TMDb cache: {str(e)}")
        return {}
    
    def _save_cache(self):
        """Save the TMDb cache to disk"""
        try:
            # Ensure cache doesn't grow too large
            if len(self.cache) > MAX_CACHE_ENTRIES:
                # Sort by timestamp and keep only the most recent entries
                sorted_items = sorted(self.cache.items(), 
                                      key=lambda x: x[1].get('timestamp', 0), 
                                      reverse=True)
                self.cache = dict(sorted_items[:MAX_CACHE_ENTRIES])
            
            # Save cache to disk
            with io.open(self.cache_file, 'w', encoding='utf8') as f:
                json.dump(self.cache, f, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving TMDb cache: {str(e)}")
    
    def _api_request(self, endpoint, params=None):
        """Make a request to the TMDb API"""
        if not self.api_key:
            return None
            
        if params is None:
            params = {}
        
        # Add API key and language to params
        params['api_key'] = self.api_key
        params['language'] = self.language
        
        # Create cache key from endpoint and params
        cache_key = json.dumps({'endpoint': endpoint, 'params': params}, sort_keys=True)
        
        # Check cache first
        if cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            # Check if cache entry is still valid
            if cache_entry.get('timestamp', 0) + CACHE_EXPIRY > time.time():
                return cache_entry.get('data')
        
        # Make API request
        try:
            url = f"{TMDB_API_URL}/{endpoint}"
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Update cache
            self.cache[cache_key] = {
                'data': data,
                'timestamp': time.time()
            }
            self._save_cache()
            
            return data
        except Exception as e:
            print(f"TMDb API error: {str(e)}")
            return None
    
    def search_movie(self, title, year=None):
        """Search for a movie by title and optional year"""
        params = {
            'query': title,
            'include_adult': str(self.include_adult).lower()
        }
        
        if year:
            params['year'] = year
            
        result = self._api_request('search/movie', params)
        if not result or not result.get('results'):
            return None
            
        return result['results'][0]  # Return the best match
    
    def get_movie_details(self, movie_id):
        """Get detailed information for a movie"""
        return self._api_request(f'movie/{movie_id}')
    
    def extract_title_year(self, filename):
        """Extract title and year from filename"""
        # Remove common quality terms and extensions
        clean_name = re.sub(r'\b(1080p|720p|480p|2160p|4k|uhd|bluray|bdrip|webrip|webdl|dvdrip|hdtv|hdcam|hdrip|xvid|aac|mp3|mp4|mkv|avi|x264|x265|hevc|h264|h265)\b', '', filename, flags=re.IGNORECASE)
        clean_name = re.sub(r'\.(mkv|avi|mp4)$', '', clean_name, flags=re.IGNORECASE)
        
        # Try to extract year
        year_match = re.search(r'(?:^|\D)(19\d{2}|20\d{2})(?:\D|$)', clean_name)
        year = year_match.group(1) if year_match else None
        
        # Remove year from title if found
        if year:
            title = clean_name.replace(year, '').strip()
        else:
            title = clean_name.strip()
        
        # Clean up remaining artifacts
        title = re.sub(r'[\._\-]', ' ', title)  # Replace dots, underscores, hyphens with spaces
        title = re.sub(r'\s+', ' ', title).strip()  # Normalize spaces
        title = re.sub(r'\[[^\]]*\]|\([^\)]*\)', '', title).strip()  # Remove content in brackets
        
        return title, year
    
    def enrich_result(self, webshare_result):
        """Enrich a Webshare search result with TMDb metadata"""
        if not self.api_key or 'name' not in webshare_result:
            return webshare_result
        
        # Extract title and year from filename
        title, year = self.extract_title_year(webshare_result['name'])
        
        # Search for movie
        movie = self.search_movie(title, year)
        if not movie:
            return webshare_result
        
        # Enrich result with metadata
        webshare_result['tmdb'] = {
            'id': movie.get('id'),
            'title': movie.get('title'),
            'original_title': movie.get('original_title'),
            'overview': movie.get('overview'),
            'release_date': movie.get('release_date'),
            'vote_average': movie.get('vote_average'),
            'poster_path': f"{TMDB_IMAGE_BASE_URL}{POSTER_SIZE}{movie.get('poster_path')}" if movie.get('poster_path') else None,
            'backdrop_path': f"{TMDB_IMAGE_BASE_URL}{BACKDROP_SIZE}{movie.get('backdrop_path')}" if movie.get('backdrop_path') else None
        }
        
        return webshare_result
    
