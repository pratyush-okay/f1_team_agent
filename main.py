#!/usr/bin/env python3
"""
CrewAI News Fetcher for F1 teams
==================================

This script uses CrewAI to fetch news articles about F1 teams from 5 trusted sports sources:
- ESPN F1
- Fox Sports  
- BBC Sport
- Sky Sports F1
- Autosport
"""

import os
import sys
import json
import requests
from datetime import datetime
from typing import Type
from pathlib import Path

# Third-party imports
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from supabase import create_client, Client

# CrewAI imports
from crewai import Agent, Crew, Process, Task
from crewai.tools import tool

# Local imports
from schemas.news_fetch import NewsFetchOutput, F1NewsAnalysisOutput

# F1 teams list
F1_TEAMS = [
    "Red Bull Racing",
    "Mercedes-AMG Petronas F1 Team",
    "Scuderia Ferrari",
    "McLaren F1 Team",
    "Alpine F1 Team",
    "Aston Martin F1 Team",
    "Haas F1 Team",
    "Williams Racing",
    "Scuderia AlphaTauri",
    "Racing Bulls F1 Team",
    "Sauber F1 Team",
]

# Simple mapping: team_id -> full_name for searching
TEAM_MAPPING = {
    "red_bull": "Red Bull Racing",
    "mercedes": "Mercedes-AMG Petronas F1 Team", 
    "ferrari": "Scuderia Ferrari",
    "mclaren": "McLaren F1 Team",
    "alpine": "Alpine F1 Team",
    "aston_martin": "Aston Martin F1 Team",
    "haas": "Haas F1 Team",
    "williams": "Williams Racing",
    "rb": "Racing Bulls F1 Team",
    "sauber": "Sauber F1 Team",
}

# Reverse mapping: full_name -> team_id for storage
TEAM_ID_MAPPING = {v: k for k, v in TEAM_MAPPING.items()}

def get_team_search_name(team_id: str) -> str:
    """Get the full team name for searching from team_id"""
    return TEAM_MAPPING.get(team_id, team_id)

def get_team_id(team_name: str) -> str:
    """Get the team_id for storage from full team name"""
    return TEAM_ID_MAPPING.get(team_name, team_name.replace(' ', '_').lower())


def setup_environment():
    """Setup project directories and environment variables"""
    print("🔧 Setting up environment...")
    
    # Load environment variables
    load_dotenv(dotenv_path=Path(".env.dev"))
    serper_api_key = os.getenv("SERPER_API_KEY")
    supabase_url = os.getenv("SUPABASE_DEV_URL")
    supabase_key = os.getenv("SUPABASE_DEV_KEY")
    
    if not serper_api_key:
        raise ValueError("Please set SERPER_API_KEY in your .env file")
    
    if not supabase_url or not supabase_key:
        raise ValueError("Please set SUPABASE_DEV_URL and SUPABASE_DEV_KEY in your .env file")
    
    print("✅ Environment setup complete!")
    return serper_api_key, supabase_url, supabase_key


def initialize_supabase(supabase_url: str, supabase_key: str) -> Client:
    """Initialize Supabase client"""
    try:
        supabase_client = create_client(supabase_url, supabase_key)
        print("✅ Supabase client initialized successfully!")
        return supabase_client
    except Exception as e:
        print(f"❌ Failed to initialize Supabase client: {str(e)}")
        raise


def upload_to_supabase(supabase_client: Client, file_content: str, file_name: str, bucket_name: str = "f1_ai_team_news") -> str:
    """
    Upload JSON content to Supabase Storage
    
    Args:
        supabase_client: Initialized Supabase client
        file_content: JSON content as string
        file_name: Name of the file to upload
        bucket_name: Supabase storage bucket name
        
    Returns:
        Public URL of the uploaded file
    """
    try:
        print(f"📤 Uploading {file_name} to Supabase Storage...")
        
        # Convert string content to bytes
        file_bytes = file_content.encode('utf-8')
        
        # Upload file to Supabase Storage with corrected options
        response = supabase_client.storage.from_(bucket_name).upload(
            path=file_name,
            file=file_bytes,
            file_options={
                "content-type": "application/json",
                "upsert": "true"  # Changed from True to "true" string
            }
        )
        
        if response:
            print(f"✅ File uploaded successfully: {file_name}")
            
            # Get public URL
            public_url = supabase_client.storage.from_(bucket_name).get_public_url(file_name)
            print(f"🔗 Public URL: {public_url}")
            return public_url
        else:
            print(f"❌ Upload failed for {file_name}")
            return None
            
    except Exception as e:
        print(f"❌ Error uploading to Supabase: {str(e)}")
        
        # Try to create bucket if it doesn't exist
        try:
            print(f"🪣 Attempting to create bucket '{bucket_name}'...")
            # Fixed bucket creation with proper parameters
            bucket_response = supabase_client.storage.create_bucket(
                bucket_name, 
                options={"public": "true"}  # Changed to string and proper structure
            )
            print(f"✅ Bucket '{bucket_name}' created successfully!")
            
            # Retry upload after creating bucket
            return upload_to_supabase(supabase_client, file_content, file_name, bucket_name)
            
        except Exception as bucket_error:
            print(f"❌ Failed to create bucket: {str(bucket_error)}")
            print("💡 Make sure your Supabase project has storage enabled and your API key has proper permissions")
            
            # Try alternative bucket creation method
            try:
                print("🔄 Trying alternative bucket creation method...")
                bucket_response = supabase_client.storage.create_bucket(bucket_name)
                print(f"✅ Bucket '{bucket_name}' created with alternative method!")
                return upload_to_supabase(supabase_client, file_content, file_name, bucket_name)
            except Exception as alt_error:
                print(f"❌ Alternative method also failed: {str(alt_error)}")
                return None


@tool("serper_news_search")
def serper_news_search(query: str) -> str:
    """Search for latest F1 news articles using Serper.dev API. Use 'site:domain.com' in query to restrict to a source."""
    headers = {
        "X-API-KEY": os.getenv("SERPER_API_KEY"),
        "Content-Type": "application/json"
    }
    try:
        response = requests.post("https://google.serper.dev/news", headers=headers, json={"q": query})
        data = response.json()

        articles = []
        for item in data.get("news", [])[:5]:
            source = "Unknown"
            if "site:" in query:
                source_part = query.split("site:")[1].split()[0]
                if "espn.com" in source_part:
                    source = "ESPN F1"
                elif "foxsports.com" in source_part:
                    source = "Fox Sports"
                elif "bbc.com" in source_part:
                    source = "BBC Sport"
                elif "skysports.com" in source_part:
                    source = "Sky Sports F1"
                elif "autosport.com" in source_part:
                    source = "Autosport"
                else:
                    source = source_part
            elif "source" in item:
                source = item["source"]

            date_str = item.get("date", "")
            try:
                if "ago" in date_str:
                    published_at = datetime.now().isoformat()
                else:
                    try:
                        from dateutil.parser import parse
                        published_at = parse(date_str).isoformat()
                    except ImportError:
                        published_at = datetime.now().isoformat()
            except Exception:
                published_at = datetime.now().isoformat()

            articles.append({
                "title": item.get("title", ""),
                "description": item.get("snippet", ""),
                "source": source,
                "published_at": published_at
            })

        return json.dumps({"articles": articles})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})


def create_f1_news_crew(team_name: str):
    """Create the F1 news crew using simple CrewAI pattern"""
    
    # Create news fetcher agent
    news_fetcher = Agent(
        role="F1 News Researcher",
        goal=f"Search and collect recent news articles about {team_name} from trusted sports sources including ESPN F1, Fox Sports, BBC Sport, Sky Sports F1, and Autosport.",
        backstory="An expert F1 digital journalist with deep knowledge of Formula 1 teams and racing dynamics. Specialized in finding credible, up-to-date F1 news from major sports outlets.",
        verbose=True,
        llm="gpt-4o",
        tools=[serper_news_search]
    )
    
    # Create news analyzer agent
    news_analyzer = Agent(
        role="F1 News Analyst",
        goal=f"Analyze collected F1 news articles about {team_name} to extract key insights, sentiment trends, and significant developments.",
        backstory="A seasoned F1 analyst with expertise in interpreting racing news, understanding team performance narratives, team dynamics, and the broader implications of F1 developments.",
        verbose=True,
        llm="gpt-4o"
    )
    
    # Create fetch news task
    fetch_task = Task(
        description=f"""
        Search and fetch recent news articles about {team_name} from multiple trusted F1 sources.
        Use the serper_news_search tool to systematically search these sources:
        - ESPN F1 (site:espn.com/f1)
        - Fox Sports (site:foxsports.com)
        - BBC Sport (site:bbc.com/sport)
        - Sky Sports F1 (site:skysports.com/f1)
        - Autosport (site:autosport.com)
        
        For each source, construct queries like "{team_name} site:espn.com/f1" to get targeted results.
        Collect at least 5-10 diverse articles with complete information.
        Focus on recent articles (last 7-14 days) when possible.
        
        Return ONLY valid JSON in this exact format:
        {{"articles":[{{"title":"Article title","description":"Article description","source":"Source name","published_at":"2024-08-20T10:00:00"}}]}}
        """,
        expected_output='{"articles":[{"title":"Article title","description":"Article description","source":"Source name","published_at":"2024-08-20T10:00:00"}]}',
        agent=news_fetcher,
        output_json=NewsFetchOutput
    )
    
    # Create analyze news task
    analyze_task = Task(
        description=f"""
        Analyze the news articles collected about {team_name} to extract key insights, sentiment trends, and significant developments.
        Select the 5 most relevant and recent articles from the fetched news.
        
        For each selected article, create a concise news summary and provide an overall analysis.
        
        Return ONLY valid JSON in this exact format:
        {{"articles":[{{"title":"Original article title","news":"2-3 sentence summary","source":"News source name","published_at":"Publication date"}}],"total_summary":"Comprehensive 3-5 sentence summary of overall sentiment, themes, developments, and media perception about {team_name}"}}
        """,
        expected_output='{"articles":[{"title":"Original article title","news":"2-3 sentence summary","source":"News source name","published_at":"Publication date"}],"total_summary":"Comprehensive summary"}',
        agent=news_analyzer,
        context=[fetch_task],
        output_json=F1NewsAnalysisOutput
    )
    
    # Create crew
    crew = Crew(
        agents=[news_fetcher, news_analyzer],
        tasks=[fetch_task, analyze_task],
        process=Process.sequential,
        verbose=True
    )
    
    return crew


def run_f1_news_analysis(team_name: str = "Red Bull Racing", supabase_client: Client = None):
    """
    Run the F1 news analysis for a specific team
    
    Args:
        team_name: Name of the F1 team to analyze
        supabase_client: Optional Supabase client for uploading results
    """
    print(f"🚀 Initializing F1 News Crew for {team_name}...")
    
    try:
        # Create crew
        crew = create_f1_news_crew(team_name)
        
        print("📰 Starting news analysis workflow...")
        print("🔍 Will search across ESPN F1, Fox Sports, BBC Sport, Sky Sports F1, and Autosport...")
        
        # Run the crew
        result = crew.kickoff()
        
        print("\n📊 Crew execution completed!")
        print("=" * 50)
        
        upload_result = None
        if result and supabase_client:
            # Convert result to JSON string for upload
            try:
                # Generate date folder and simple filename using team_id
                current_date = datetime.now().strftime("%Y-%m-%d")
                team_id = get_team_id(team_name)
                team_filename = f"{team_id}.json"
                file_path = f"{current_date}/{team_filename}"
                
                # Extract the raw field content if it exists, otherwise use the full result
                if hasattr(result, 'raw') and result.raw:
                    # Use the raw field content directly
                    json_content = result.raw
                elif hasattr(result, 'model_dump'):
                    # Pydantic model
                    result_dict = result.model_dump()
                    json_content = json.dumps(result_dict, indent=2, ensure_ascii=False)
                elif hasattr(result, 'dict'):
                    # Pydantic v1 model
                    result_dict = result.dict()
                    json_content = json.dumps(result_dict, indent=2, ensure_ascii=False)
                else:
                    # Fallback for other types
                    result_dict = {
                        "team_name": team_name,
                        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                        "result": str(result)
                    }
                    json_content = json.dumps(result_dict, indent=2, ensure_ascii=False)
                
                # Upload to Supabase
                upload_result = upload_to_supabase(supabase_client, json_content, file_path, "f1_ai_team_news")
                
            except Exception as upload_error:
                print(f"❌ Error preparing upload: {str(upload_error)}")
                upload_result = None
        
        # Display results
        if result:
            print("✅ Results generated successfully!")
            
            # Handle different result types
            if isinstance(result, str):
                # Try to parse as JSON if it's a string
                try:
                    parsed_result = json.loads(result)
                    if 'articles' in parsed_result:
                        articles = parsed_result['articles']
                        print(f"\n📰 Final Analysis: {len(articles)} articles")
                        for i, article in enumerate(articles, 1):
                            print(f"\n{i}. {article.get('title', 'No title')[:80]}...")
                            print(f"   Source: {article.get('source', 'Unknown')}")
                            if 'news' in article:
                                print(f"   Summary: {article['news'][:100]}...")
                        
                        if 'total_summary' in parsed_result:
                            print(f"\n📊 Total Summary:")
                            print(f"   {parsed_result['total_summary'][:150]}...")
                    else:
                        print("\n📋 Parsed Result:")
                        print(str(parsed_result)[:200] + "..." if len(str(parsed_result)) > 200 else str(parsed_result))
                except json.JSONDecodeError:
                    print("\n📋 Raw Result (string):")
                    print(str(result)[:200] + "..." if len(str(result)) > 200 else str(result))
            elif hasattr(result, 'articles') and result.articles:
                # Handle Pydantic model result
                print(f"\n📰 Final Analysis: {len(result.articles)} articles")
                for i, article in enumerate(result.articles, 1):
                    print(f"\n{i}. {article.title[:80]}...")
                    print(f"   Source: {article.source}")
                    if hasattr(article, 'news'):
                        print(f"   Summary: {article.news[:100]}...")
                    elif hasattr(article, 'description'):
                        print(f"   Description: {article.description[:100]}...")
                
                if hasattr(result, 'total_summary'):
                    print(f"\n📊 Total Summary:")
                    print(f"   {result.total_summary[:150]}...")
            else:
                print("\n📋 Result:")
                print(str(result)[:200] + "..." if len(str(result)) > 200 else str(result))
                
            return result, upload_result
        else:
            print("⚠️ No results returned")
            return None, None
        
    except Exception as e:
        print(f"❌ Error during execution: {str(e)}")
        print("\nTroubleshooting:")
        print("1. Check SERPER_API_KEY is set in .env file") 
        print("2. Check SUPABASE_DEV_URL and SUPABASE_DEV_KEY are set in .env file")
        print("3. Ensure internet connection is available")
        print("4. Make sure schemas/news_fetch.py exists with NewsFetchOutput")
        return None, None


def main():
    """Main function to run the F1 news analysis for all teams"""
    try:
        # Setup environment
        serper_api_key, supabase_url, supabase_key = setup_environment()
        
        # Initialize Supabase client
        try:
            supabase_client = initialize_supabase(supabase_url, supabase_key)
        except Exception as e:
            print(f"⚠️ Supabase initialization failed: {str(e)}")
            print("📝 Continuing without Supabase upload...")
            supabase_client = None
        
        # Check if specific team is provided as argument
        if len(sys.argv) > 1:
            # Run for specific team
            team_name = sys.argv[1]
            print(f"🏎️ F1 News Analysis for {team_name}")
            print("=" * 50)
            
            result, upload_result = run_f1_news_analysis(team_name, supabase_client)
            
            if result:
                print(f"\n🎉 Analysis complete for {team_name}!")
                if upload_result and supabase_client:
                    print(f"🌐 Analysis uploaded to Supabase: {upload_result}")
                else:
                    print("⚠️ Analysis not uploaded to Supabase")
            else:
                print(f"\n❌ Analysis failed for {team_name}")
                sys.exit(1)
        else:
            # Run for all teams
            print(f"🏎️ F1 News Analysis for ALL {len(F1_TEAMS)} teams")
            print("=" * 60)
            
            successful_analyses = 0
            failed_analyses = 0
            
            for i, team_name in enumerate(F1_TEAMS, 1):
                print(f"\n📊 Processing {i}/{len(F1_TEAMS)}: {team_name}")
                print("-" * 40)
                
                try:
                    result, upload_result = run_f1_news_analysis(team_name, supabase_client)
                    
                    if result:
                        successful_analyses += 1
                        print(f"✅ Analysis complete for {team_name}")
                        if upload_result and supabase_client:
                            print(f"🌐 Uploaded: {upload_result}")
                    else:
                        failed_analyses += 1
                        print(f"❌ Analysis failed for {team_name}")
                        
                except Exception as e:
                    failed_analyses += 1
                    print(f"❌ Error processing {team_name}: {str(e)}")
                    continue
            
            # Summary
            print(f"\n🎉 BATCH ANALYSIS COMPLETE!")
            print("=" * 60)
            print(f"✅ Successful: {successful_analyses}/{len(F1_TEAMS)}")
            print(f"❌ Failed: {failed_analyses}/{len(F1_TEAMS)}")
            
            if failed_analyses > 0:
                print(f"⚠️ {failed_analyses} analyses failed. Check logs above.")
            
    except KeyboardInterrupt:
        print("\n🛑 Analysis interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()