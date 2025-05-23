# -*- coding: utf-8 -*-
# Module: series_manager
# Author: user extension
# Created on: 5.6.2023
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html

import os
import io
import re
import json
import xbmc
import xbmcaddon
import xbmcgui
import xml.etree.ElementTree as ET

try:
    from urllib import urlencode
    from urlparse import parse_qsl
except ImportError:
    from urllib.parse import urlencode
    from urllib.parse import parse_qsl

try:
    from xbmc import translatePath
except ImportError:
    from xbmcvfs import translatePath

# Regular expressions for detecting episode patterns
EPISODE_PATTERNS = [
    r'[Ss](\d+)[Ee](\d+)',  # S01E01 format
    r'(\d+)x(\d+)',         # 1x01 format
    r'[Ee]pisode\s*(\d+)',  # Episode 1 format
    r'[Ee]p\s*(\d+)',       # Ep 1 format
    r'[Ee](\d+)',           # E1 format
    r'(\d+)\.\s*(\d+)'      # 1.01 format
]

class SeriesManager:
    def __init__(self, addon, profile):
        self.addon = addon
        self.profile = profile
        self.series_db_path = os.path.join(profile, 'series_db')
        self.ensure_db_exists()
        
    def ensure_db_exists(self):
        """Ensure that the series database directory exists"""
        try:
            if not os.path.exists(self.profile):
                os.makedirs(self.profile)
            if not os.path.exists(self.series_db_path):
                os.makedirs(self.series_db_path)
        except Exception as e:
            xbmc.log(f'YaWSP Series Manager: Error creating directories: {str(e)}', level=xbmc.LOGERROR)
    
    def search_series(self, series_name, api_function, token):
        """Search for episodes of a series"""
        # Structure to hold results
        series_data = {
            'name': series_name,
            'last_updated': xbmc.getInfoLabel('System.Date'),
            'seasons': {}
        }
        
        # Define search queries to try
        search_queries = [
            series_name,                    # exact name
            f"{series_name} season",        # name + season
            f"{series_name} s01",           # name + s01
            f"{series_name} episode"        # name + episode
        ]
        
        all_results = []
        
        # Try each search query
        for query in search_queries:
            results = self._perform_search(query, api_function, token)
            # Add results to our collection, avoiding duplicates
            for result in results:
                if result not in all_results and self._is_likely_episode(result['name'], series_name):
                    all_results.append(result)
        
        # Process results and organize into seasons
        for item in all_results:
            season_num, episode_num = self._detect_episode_info(item['name'], series_name)
            if season_num is not None:
                # Convert to strings for JSON compatibility
                season_num_str = str(season_num)
                episode_num_str = str(episode_num)
                
                if season_num_str not in series_data['seasons']:
                    series_data['seasons'][season_num_str] = {}
                
                series_data['seasons'][season_num_str][episode_num_str] = {
                    'name': item['name'],
                    'ident': item['ident'],
                    'size': item.get('size', '0')
                }
        
        # Save the series data
        self._save_series_data(series_name, series_data)
        
        return series_data
    
    def _is_likely_episode(self, filename, series_name):
        """Check if a filename is likely to be an episode of the series"""
        # Skip if doesn't contain series name
        if not re.search(re.escape(series_name), filename, re.IGNORECASE):
            return False
            
        # Positive indicators
        for pattern in EPISODE_PATTERNS:
            if re.search(pattern, filename, re.IGNORECASE):
                return True
                
        # Keywords that suggest it's a episode
        episode_keywords = [
            'episode', 'season', 'series', 'ep', 
            'complete', 'serie', 'season', 'disk'
        ]
        
        for keyword in episode_keywords:
            if keyword in filename.lower():
                return True
                
        return False
    
    def _perform_search(self, search_query, api_function, token):
        """Perform the actual search using the provided API function"""
        results = []
        
        # Call the Webshare API to search for the series
        response = api_function('search', {
            'what': search_query, 
            'category': 'video', 
            'sort': 'recent',
            'limit': 100,  # Get a good number of results to find episodes
            'offset': 0,
            'wst': token,
            'maybe_removed': 'true'
        })
        
        xml = ET.fromstring(response.content)
        
        # Check if the search was successful
        status = xml.find('status')
        if status is not None and status.text == 'OK':
            # Convert XML to a list of dictionaries
            for file in xml.iter('file'):
                item = {}
                for elem in file:
                    item[elem.tag] = elem.text
                results.append(item)
        
        return results
    
    def _detect_episode_info(self, filename, series_name):
        """Try to detect season and episode numbers from filename"""
        # Remove series name and clean up the string
        cleaned = filename.lower().replace(series_name.lower(), '').strip()
        
        # Try each of our patterns
        for pattern in EPISODE_PATTERNS:
            match = re.search(pattern, cleaned)
            if match:
                groups = match.groups()
                if len(groups) == 2:  # Patterns like S01E02
                    return int(groups[0]), int(groups[1])
                elif len(groups) == 1:  # Patterns like Episode 5
                    # Assume season 1 if only episode number is found
                    return 1, int(groups[0])
        
        # If no match found, try to infer from the filename
        if 'season' in cleaned.lower() or 'serie' in cleaned.lower():
            # Try to find season number
            season_match = re.search(r'season\s*(\d+)', cleaned.lower())
            if season_match:
                season_num = int(season_match.group(1))
                # Try to find episode number
                ep_match = re.search(r'(\d+)', cleaned.replace(season_match.group(0), ''))
                if ep_match:
                    return season_num, int(ep_match.group(1))
        
        # Default fallback
        return None, None
    
    def _save_series_data(self, series_name, series_data):
        """Save series data to the database"""
        safe_name = self._safe_filename(series_name)
        file_path = os.path.join(self.series_db_path, f"{safe_name}.json")
        
        try:
            with io.open(file_path, 'w', encoding='utf8') as file:
                try:
                    data = json.dumps(series_data, indent=2).decode('utf8')
                except AttributeError:
                    data = json.dumps(series_data, indent=2)
                file.write(data)
                file.close()
        except Exception as e:
            xbmc.log(f'YaWSP Series Manager: Error saving series data: {str(e)}', level=xbmc.LOGERROR)
    
    def load_series_data(self, series_name):
        """Load series data from the database"""
        safe_name = self._safe_filename(series_name)
        file_path = os.path.join(self.series_db_path, f"{safe_name}.json")
        
        if not os.path.exists(file_path):
            return None
        
        try:
            with io.open(file_path, 'r', encoding='utf8') as file:
                data = file.read()
                file.close()
                try:
                    series_data = json.loads(data, "utf-8")
                except TypeError:
                    series_data = json.loads(data)
                return series_data
        except Exception as e:
            xbmc.log(f'YaWSP Series Manager: Error loading series data: {str(e)}', level=xbmc.LOGERROR)
            return None
    
    def get_all_series(self):
        """Get a list of all saved series"""
        series_list = []
        
        try:
            for filename in os.listdir(self.series_db_path):
                if filename.endswith('.json'):
                    series_name = os.path.splitext(filename)[0]
                    # Convert safe filename back to proper name (rough conversion)
                    proper_name = series_name.replace('_', ' ')
                    series_list.append({
                        'name': proper_name,
                        'filename': filename,
                        'safe_name': series_name
                    })
        except Exception as e:
            xbmc.log(f'YaWSP Series Manager: Error listing series: {str(e)}', level=xbmc.LOGERROR)
        
        return series_list
    
    def _safe_filename(self, name):
        """Convert a series name to a safe filename"""
        # Replace problematic characters
        safe = re.sub(r'[^\w\-_\. ]', '_', name)
        return safe.lower().replace(' ', '_')

# Utility functions for the UI layer
def get_url(**kwargs):
    """Create a URL for calling the plugin recursively"""
    from yawsp import _url
    return '{0}?{1}'.format(_url, urlencode(kwargs, 'utf-8'))

def create_series_menu(series_manager, handle):
    """Create the series selection menu"""
    import xbmcplugin
    
    # Add "Search for new series" option
    listitem = xbmcgui.ListItem(label="Hledat novy serial")
    listitem.setArt({'icon': 'DefaultAddSource.png'})
    xbmcplugin.addDirectoryItem(handle, get_url(action='series_search'), listitem, True)
    
    # List existing series
    series_list = series_manager.get_all_series()
    for series in series_list:
        listitem = xbmcgui.ListItem(label=series['name'])
        listitem.setArt({'icon': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(handle, get_url(action='series_detail', series_name=series['name']), listitem, True)
    
    xbmcplugin.endOfDirectory(handle)

def create_seasons_menu(series_manager, handle, series_name):
    """Create menu of seasons for a series"""
    import xbmcplugin
    
    series_data = series_manager.load_series_data(series_name)
    if not series_data:
        xbmcgui.Dialog().notification('YaWSP', 'Data serialu nenalezena', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return
    
    # Add "Refresh series" option
    listitem = xbmcgui.ListItem(label="Aktualizovat serial")
    listitem.setArt({'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle, get_url(action='series_refresh', series_name=series_name), listitem, True)
    
    # List seasons
    for season_num in sorted(series_data['seasons'].keys(), key=int):
        season_name = f"Rada {season_num}"
        listitem = xbmcgui.ListItem(label=season_name)
        listitem.setArt({'icon': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(handle, get_url(action='series_season', series_name=series_name, season=season_num), listitem, True)
    
    xbmcplugin.endOfDirectory(handle)

def create_episodes_menu(series_manager, handle, series_name, season_num):
    """Create menu of episodes for a season"""
    import xbmcplugin
    
    series_data = series_manager.load_series_data(series_name)
    if not series_data or str(season_num) not in series_data['seasons']:
        xbmcgui.Dialog().notification('YaWSP', 'Data sezony nenalezena', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return
    
    # Convert season_num to a string for dict lookup if it's not already
    season_num = str(season_num)
    
    # List episodes
    season = series_data['seasons'][season_num]
    for episode_num in sorted(season.keys(), key=int):
        episode = season[episode_num]
        episode_name = f"Epizoda {episode_num} - {episode['name']}"
        
        listitem = xbmcgui.ListItem(label=episode_name)
        listitem.setArt({'icon': 'DefaultVideo.png'})
        listitem.setProperty('IsPlayable', 'true')
        
        # Generate URL for playing this episode
        url = get_url(action='play', ident=episode['ident'], name=episode['name'])
        
        xbmcplugin.addDirectoryItem(handle, url, listitem, False)
    
    xbmcplugin.endOfDirectory(handle) 
