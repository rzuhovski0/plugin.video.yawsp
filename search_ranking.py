import datetime
import re

import tmdb

def score_result(file_info, search_query=None):
    """
    Score a search result based on quality indicators in filename and metadata.
    Higher score = better quality/more relevant result.
    
    Args:
        file_info (dict): Dictionary with file information
        search_query (str, optional): The search query for relevance scoring
        
    Returns:
        float: Quality and relevance score (higher is better)
    """
    if not file_info or 'name' not in file_info:
        return 0
        
    name = file_info['name'].lower()
    score = 0
    
    # Resolution scoring
    if re.search(r'[^0-9](2160p|4k|uhd)[^0-9]', name):
        score += 100
    elif re.search(r'[^0-9]1080p[^0-9]', name):
        score += 80
    elif re.search(r'[^0-9]720p[^0-9]', name):
        score += 60
    elif re.search(r'[^0-9]480p[^0-9]', name):
        score += 20
    
    # Source quality scoring
    if re.search(r'(blu[\s\.\-]*ray|bdrip|bd[\s\.\-]*rip)', name):
        score += 50
    elif re.search(r'(web[\s\.\-]*rip|web[\s\.\-]*dl)', name):
        score += 40
    elif re.search(r'(dvdrip|dvd[\s\.\-]*rip)', name):
        score += 30
    elif re.search(r'hdtv', name):
        score += 20
    
    # Audio quality
    if re.search(r'(atmos|dolby|dts|aac5)', name):
        score += 15
    
    # Encoding quality
    if re.search(r'x265|hevc|h265', name):
        score += 15
    elif re.search(r'x264|h264', name):
        score += 10
    
    # Release group scoring - known good groups
    if re.search(r'(sparks|geckos|yify|yts|rarbg|ctrlhd)', name):
        score += 10
    
    # Penalize low quality indicators
    if re.search(r'[^a-z]cam[^a-z]|camrip', name):
        score -= 100
    if re.search(r'[^a-z]ts[^a-z]|telesync', name):
        score -= 80
    if re.search(r'hdcam', name):
        score -= 50
    if re.search(r'screener|scr', name):
        score -= 40
    if re.search(r'hardcoded|hc', name) and re.search(r'sub', name):
        score -= 20  # Hardcoded subtitles
    
    # Boost for proper releases
    if re.search(r'proper|repack', name):
        score += 10
        
    # Penalize poor audio
    if re.search(r'[^a-z]mic[^a-z]|line', name) and not re.search(r'online', name):
        score -= 30
    
    # File size consideration (larger files tend to be better quality for video)
    try:
        if 'size' in file_info:
            size_mb = int(file_info['size']) / (1024 * 1024)  # Convert to MB
            # Give a small bonus for larger files (max 25 points)
            score += min(size_mb / 1000, 25)
    except (ValueError, TypeError):
        pass
    
    # Title relevance scoring (when search_query is provided)
    if search_query and search_query.lower() != '%#none#%':
        search_terms = search_query.lower().split()
        
        # Remove common words that don't help in matching
        search_terms = [t for t in search_terms if len(t) > 2 and t not in ('the', 'and', 'for', 'with')]
        
        # Exact title match (case insensitive)
        if search_query.lower() in name:
            score += 200
        
        # Count matching terms and their positions
        matched_terms = 0
        for i, term in enumerate(search_terms):
            if term in name:
                matched_terms += 1
                # Terms at the beginning of the query are more important
                term_weight = 1.0 - (i * 0.1) if i < 5 else 0.5
                score += 30 * term_weight
        
        # Perfect match (all terms in the correct order)
        if matched_terms == len(search_terms) and ' '.join(search_terms) in name:
            score += 100
        
        # Boost if the title starts with the search query
        if any(name.startswith(term) for term in search_terms):
            score += 50
            
        # Penalize results with many extra words (likely less relevant)
        name_words = len(name.split())
        query_words = len(search_terms)
        if name_words > query_words * 3:
            score -= min((name_words - query_words*2) * 5, 50)
        
        # Year matching bonus (if year is in search query)
        year_match = re.search(r'\b(19|20)\d{2}\b', search_query)
        if year_match:
            year = year_match.group(0)
            if year in name:
                score += 50
    
    return score

def should_include_result(file_info, filters):
    """
    Check if a result should be included based on user filters
    
    Args:
        file_info (dict): Dictionary with file information
        filters (dict): Dictionary with filter settings
        
    Returns:
        bool: True if the result should be included, False otherwise
    """
    if not file_info or 'name' not in file_info:
        return False
        
    name = file_info['name'].lower()
    
    # Apply resolution filter
    min_res = filters.get('min_resolution', 0)
    if min_res == 1 and not any(res in name for res in ['480p', '720p', '1080p', '2160p', '4k', 'uhd']):
        return False
    elif min_res == 2 and not any(res in name for res in ['720p', '1080p', '2160p', '4k', 'uhd']):
        return False
    elif min_res == 3 and not any(res in name for res in ['1080p', '2160p', '4k', 'uhd']):
        return False
    elif min_res == 4 and not any(res in name for res in ['2160p', '4k', 'uhd']):
        return False
    
    # Exclude CAM/TS if enabled
    if filters.get('exclude_cam', True):
        low_quality_terms = ['cam', 'camrip', '[cam]', 'ts', 'telesync', 'hdcam']
        if any(term in name for term in low_quality_terms):
            return False
    
    # Filter by age if set
    max_age = filters.get('max_age', 0)
    if max_age > 0 and 'created' in file_info:
        try:
            created_date = datetime.datetime.strptime(file_info['created'], '%Y-%m-%d %H:%M:%S')
            now = datetime.datetime.now()
            age_months = (now.year - created_date.year) * 12 + (now.month - created_date.month)
            if age_months > max_age:
                return False
        except (ValueError, TypeError):
            pass
    
    return True

def filter_and_sort_results(files, search_query=None, filters=None, tmdb_api=None):
    """
    Filter and sort search results by quality and relevance
    
    Args:
        files (list): List of file dictionaries to sort
        search_query (str, optional): The search query for relevance scoring
        filters (dict, optional): Dictionary with filter settings
        tmdb_api (TMDbAPI, optional): TMDb API instance for metadata enrichment
        
    Returns:
        list: Filtered and sorted list of file dictionaries
    """
    if filters is None:
        filters = {}
        
    # Filter results
    filtered_files = [f for f in files if should_include_result(f, filters)]
    
    # Sort results by quality score
    sorted_files = sorted(filtered_files, 
                  key=lambda x: score_result(x, search_query), 
                  reverse=True)
    
    # Enrich with TMDb metadata if API is available
    if tmdb_api and filters.get('enrich_metadata', True):
        for i, file_info in enumerate(sorted_files):
            # Only enrich the top N results to minimize API calls
            if i < 20:  # Process only top 20 results
                sorted_files[i] = tmdb_api.enrich_result(file_info)
    
    return sorted_files