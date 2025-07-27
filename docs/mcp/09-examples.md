# Model Context Protocol (MCP) - Examples

## Table of Contents
- [Overview](#overview)
- [Complete Server Examples](#complete-server-examples)
- [Complete Client Examples](#complete-client-examples)
- [Real-World Implementations](#real-world-implementations)
- [Integration Examples](#integration-examples)
- [Advanced Patterns](#advanced-patterns)
- [Troubleshooting Common Issues](#troubleshooting-common-issues)

## Overview

This document provides practical examples of MCP implementations, from simple servers and clients to complex real-world integrations. Each example includes complete, runnable code with explanations.

## Complete Server Examples

### 1. File System Server

A complete MCP server that provides file system access with security controls.

```python
# filesystem_server.py
import os
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from mcp.server.fastmcp import FastMCP
import aiofiles

# Create server instance
mcp = FastMCP(
    name="filesystem-server",
    version="1.0.0"
)

# Configuration
ALLOWED_DIRECTORIES = [
    str(Path.home() / "Documents"),
    str(Path.home() / "Desktop"),
]

# Helper to validate paths
def is_path_allowed(file_path: str) -> bool:
    """Check if path is within allowed directories"""
    absolute_path = Path(file_path).resolve()
    return any(
        str(absolute_path).startswith(str(Path(dir).resolve()))
        for dir in ALLOWED_DIRECTORIES
    )

# List available resources (files)
@mcp.list_resources()
async def list_resources() -> List[Dict[str, Any]]:
    """List available files as resources"""
    resources = []
    
    for dir_path in ALLOWED_DIRECTORIES:
        try:
            path = Path(dir_path)
            if path.exists():
                for file in path.iterdir():
                    if file.is_file():
                        resources.append({
                            "uri": f"file://{file}",
                            "name": file.name,
                            "mimeType": get_mime_type(file.name),
                        })
        except Exception:
            # Directory might not exist or be accessible
            pass
    
    return resources

# Read file content
@mcp.resource("file://*")
async def read_file_resource(uri: str) -> str:
    """Read file content from URI"""
    file_path = uri.replace("file://", "")
    
    if not is_path_allowed(file_path):
        raise ValueError("Access denied: Path not allowed")
    
    async with aiofiles.open(file_path, 'r') as f:
        content = await f.read()
    
    return content

# File manipulation tools
@mcp.tool(
    name="create_file",
    description="Create a new file",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path",
            },
            "content": {
                "type": "string",
                "description": "File content",
            },
        },
        "required": ["path", "content"],
    }
)
async def create_file(path: str, content: str) -> str:
    """Create a new file with content"""
    if not is_path_allowed(path):
        raise ValueError("Access denied: Path not allowed")
    
    async with aiofiles.open(path, 'w') as f:
        await f.write(content)
    
    return f"File created: {path}"

@mcp.tool(
    name="append_to_file",
    description="Append content to an existing file",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path",
            },
            "content": {
                "type": "string",
                "description": "Content to append",
            },
        },
        "required": ["path", "content"],
    }
)
async def append_to_file(path: str, content: str) -> str:
    """Append content to an existing file"""
    if not is_path_allowed(path):
        raise ValueError("Access denied: Path not allowed")
    
    async with aiofiles.open(path, 'a') as f:
        await f.write(content)
    
    return f"Content appended to: {path}"

@mcp.tool(
    name="delete_file",
    description="Delete a file",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path",
            },
        },
        "required": ["path"],
    }
)
async def delete_file(path: str) -> str:
    """Delete a file"""
    if not is_path_allowed(path):
        raise ValueError("Access denied: Path not allowed")
    
    Path(path).unlink()
    return f"File deleted: {path}"

@mcp.tool(
    name="list_directory",
    description="List contents of a directory",
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path",
            },
        },
        "required": ["path"],
    }
)
async def list_directory(path: str) -> str:
    """List contents of a directory"""
    if not is_path_allowed(path):
        raise ValueError("Access denied: Path not allowed")
    
    directory = Path(path)
    if not directory.is_dir():
        raise ValueError(f"Not a directory: {path}")
    
    listing = []
    for item in directory.iterdir():
        listing.append({
            "name": item.name,
            "type": "directory" if item.is_dir() else "file",
        })
    
    return json.dumps(listing, indent=2)

# Helper functions
def get_mime_type(filename: str) -> str:
    """Get MIME type from file extension"""
    ext = Path(filename).suffix.lower()
    mime_types = {
        ".txt": "text/plain",
        ".json": "application/json",
        ".js": "text/javascript",
        ".ts": "text/typescript",
        ".py": "text/x-python",
        ".md": "text/markdown",
        ".html": "text/html",
        ".css": "text/css",
    }
    return mime_types.get(ext, "application/octet-stream")

# Start server
if __name__ == "__main__":
    print("Filesystem MCP server running", file=sys.stderr)
    mcp.run()
```

### 2. Database Server

An MCP server that provides database access with query capabilities.

```python
# database_server.py
import asyncio
import json
import sqlite3
import sys
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
from pathlib import Path

# Create server instance
mcp = FastMCP(
    name="database-server",
    version="1.0.0"
)

# Global database path
DB_PATH = "sample.db"

@mcp.list_resources()
async def list_resources() -> List[Dict[str, Any]]:
    """List available database tables as resources"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = cursor.fetchall()
    conn.close()
    
    return [
        {
            "uri": f"db://{DB_PATH}/{table[0]}",
            "name": f"Table: {table[0]}",
            "mimeType": "application/json",
        }
        for table in tables
    ]

@mcp.resource("db://*/*")
async def read_table_resource(uri: str) -> str:
    """Read table schema and sample data"""
    # Parse URI
    parts = uri.replace("db://", "").split("/")
    table_name = parts[-1]
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get table schema
    cursor.execute(f"PRAGMA table_info({table_name})")
    schema = [dict(row) for row in cursor.fetchall()]
    
    # Get sample data
    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
    sample_data = [dict(row) for row in cursor.fetchall()]
    
    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    row_count = cursor.fetchone()[0]
    
    conn.close()
    
    result = {
        "table": table_name,
        "schema": schema,
        "row_count": row_count,
        "sample_data": sample_data
    }
    
    return json.dumps(result, indent=2)

@mcp.tool(
    name="query",
    description="Execute a SELECT query",
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "SELECT query to execute"
            },
            "parameters": {
                "type": "array",
                "description": "Query parameters",
                "items": {"type": ["string", "number", "null"]}
            }
        },
        "required": ["sql"]
    }
)
async def query_database(sql: str, parameters: Optional[List[Any]] = None) -> str:
    """Execute a SELECT query"""
    # Validate it's a SELECT query
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        raise ValueError("Only SELECT queries allowed")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Execute query
        params = parameters or []
        cursor.execute(sql, params)
        
        # Fetch results
        results = [dict(row) for row in cursor.fetchall()]
        
        return json.dumps({
            "row_count": len(results),
            "results": results
        }, indent=2)
        
    finally:
        conn.close()

@mcp.tool(
    name="execute",
    description="Execute INSERT, UPDATE, or DELETE",
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "SQL statement to execute"
            },
            "parameters": {
                "type": "array",
                "description": "Statement parameters",
                "items": {"type": ["string", "number", "null"]}
            }
        },
        "required": ["sql"]
    }
)
async def execute_statement(sql: str, parameters: Optional[List[Any]] = None) -> str:
    """Execute INSERT, UPDATE, or DELETE statement"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Execute statement
        params = parameters or []
        cursor.execute(sql, params)
        conn.commit()
        
        return f"Executed successfully. Rows affected: {cursor.rowcount}"
        
    finally:
        conn.close()

@mcp.tool(
    name="create_table",
    description="Create a new table",
    parameters={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Name of the table"
            },
            "columns": {
                "type": "array",
                "description": "Column definitions",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "primary_key": {"type": "boolean"},
                        "not_null": {"type": "boolean"}
                    },
                    "required": ["name", "type"]
                }
            }
        },
        "required": ["table_name", "columns"]
    }
)
async def create_table(table_name: str, columns: List[Dict[str, Any]]) -> str:
    """Create a new table"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Build CREATE TABLE statement
        column_defs = []
        for col in columns:
            col_def = f"{col['name']} {col['type']}"
            if col.get("primary_key"):
                col_def += " PRIMARY KEY"
            if col.get("not_null"):
                col_def += " NOT NULL"
            column_defs.append(col_def)
        
        sql = f"CREATE TABLE {table_name} ({', '.join(column_defs)})"
        cursor.execute(sql)
        conn.commit()
        
        return f"Table '{table_name}' created successfully"
        
    finally:
        conn.close()

# Initialize with sample database
def init_sample_db():
    """Initialize sample database with test data"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create sample tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0
        )
    """)
    
    # Insert sample data
    cursor.executemany(
        "INSERT OR IGNORE INTO users (name, email) VALUES (?, ?)",
        [
            ("Alice Smith", "alice@example.com"),
            ("Bob Johnson", "bob@example.com"),
            ("Charlie Brown", "charlie@example.com")
        ]
    )
    
    cursor.executemany(
        "INSERT OR IGNORE INTO products (name, price, stock) VALUES (?, ?, ?)",
        [
            ("Widget", 9.99, 100),
            ("Gadget", 19.99, 50),
            ("Doohickey", 14.99, 75)
        ]
    )
    
    conn.commit()
    conn.close()

# Start server
if __name__ == "__main__":
    init_sample_db()
    print(f"Database MCP server running with {DB_PATH}", file=sys.stderr)
    mcp.run()
```

### 3. API Integration Server

An MCP server that integrates with external APIs.

```python
# api_server.py
import os
import sys
import json
import asyncio
from typing import List, Dict, Any, Optional
import aiohttp
from mcp.server.fastmcp import FastMCP

# Create server instance
mcp = FastMCP(
    name="api-integration-server",
    version="1.0.0"
)

# API configurations
APIS = {
    "weather": {
        "base_url": "https://api.openweathermap.org/data/2.5",
        "api_key": os.getenv("OPENWEATHER_API_KEY"),
    },
    "github": {
        "base_url": "https://api.github.com",
        "token": os.getenv("GITHUB_TOKEN"),
    },
}

# API documentation resources
@mcp.list_resources()
async def list_resources() -> List[Dict[str, Any]]:
    """List API documentation resources"""
    return [
        {
            "uri": "api://weather/docs",
            "name": "Weather API Documentation",
            "mimeType": "text/markdown",
        },
        {
            "uri": "api://github/docs",
            "name": "GitHub API Documentation",
            "mimeType": "text/markdown",
        },
    ]

@mcp.resource("api://*/docs")
async def read_api_docs(uri: str) -> str:
    """Read API documentation"""
    docs = {
        "api://weather/docs": """# Weather API

Available endpoints:
- Get current weather: `weather?q={city}`
- Get forecast: `forecast?q={city}`

Example usage with the MCP tool:
- Tool: get_weather
- Arguments: { "city": "London" }""",
        
        "api://github/docs": """# GitHub API

Available endpoints:
- Get user repos: `/users/{username}/repos`
- Get repo info: `/repos/{owner}/{repo}`
- Create issue: `/repos/{owner}/{repo}/issues`

Example usage with MCP tools:
- Tool: github_user_repos
- Arguments: { "username": "octocat" }""",
    }
    
    return docs.get(uri, "Documentation not found")

# Weather API tools
@mcp.tool(
    name="get_weather",
    description="Get current weather for a city",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name",
            },
            "units": {
                "type": "string",
                "enum": ["metric", "imperial"],
                "default": "metric",
                "description": "Temperature units",
            },
        },
        "required": ["city"],
    }
)
async def get_weather(city: str, units: str = "metric") -> str:
    """Get current weather for a city"""
    async with aiohttp.ClientSession() as session:
        params = {
            "q": city,
            "units": units,
            "appid": APIS["weather"]["api_key"],
        }
        
        async with session.get(
            f"{APIS['weather']['base_url']}/weather",
            params=params
        ) as response:
            data = await response.json()
            
            if response.status != 200:
                raise ValueError(f"Weather API error: {data.get('message', 'Unknown error')}")
            
            result = {
                "city": data["name"],
                "country": data["sys"]["country"],
                "temperature": data["main"]["temp"],
                "feels_like": data["main"]["feels_like"],
                "description": data["weather"][0]["description"],
                "humidity": data["main"]["humidity"],
                "wind_speed": data["wind"]["speed"],
            }
            
            return json.dumps(result, indent=2)

@mcp.tool(
    name="get_forecast",
    description="Get 5-day weather forecast",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name",
            },
            "units": {
                "type": "string",
                "enum": ["metric", "imperial"],
                "default": "metric",
                "description": "Temperature units",
            },
        },
        "required": ["city"],
    }
)
async def get_forecast(city: str, units: str = "metric") -> str:
    """Get 5-day weather forecast"""
    async with aiohttp.ClientSession() as session:
        params = {
            "q": city,
            "units": units,
            "appid": APIS["weather"]["api_key"],
        }
        
        async with session.get(
            f"{APIS['weather']['base_url']}/forecast",
            params=params
        ) as response:
            data = await response.json()
            
            if response.status != 200:
                raise ValueError(f"Weather API error: {data.get('message', 'Unknown error')}")
            
            forecasts = [
                {
                    "datetime": item["dt_txt"],
                    "temperature": item["main"]["temp"],
                    "description": item["weather"][0]["description"],
                }
                for item in data["list"][:5]
            ]
            
            return json.dumps(forecasts, indent=2)

# GitHub API tools
@mcp.tool(
    name="github_user_repos",
    description="Get repositories for a GitHub user",
    parameters={
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "GitHub username",
            },
            "sort": {
                "type": "string",
                "enum": ["created", "updated", "pushed", "full_name"],
                "description": "Sort order",
            },
        },
        "required": ["username"],
    }
)
async def github_user_repos(username: str, sort: Optional[str] = None) -> str:
    """Get repositories for a GitHub user"""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"token {APIS['github']['token']}",
            "Accept": "application/vnd.github.v3+json",
        }
        params = {"per_page": 10}
        if sort:
            params["sort"] = sort
        
        async with session.get(
            f"{APIS['github']['base_url']}/users/{username}/repos",
            headers=headers,
            params=params
        ) as response:
            data = await response.json()
            
            if response.status != 200:
                raise ValueError(f"GitHub API error: {data.get('message', 'Unknown error')}")
            
            repos = [
                {
                    "name": repo["name"],
                    "description": repo["description"],
                    "stars": repo["stargazers_count"],
                    "language": repo["language"],
                    "url": repo["html_url"],
                }
                for repo in data
            ]
            
            return json.dumps(repos, indent=2)

@mcp.tool(
    name="github_repo_info",
    description="Get information about a GitHub repository",
    parameters={
        "type": "object",
        "properties": {
            "owner": {
                "type": "string",
                "description": "Repository owner",
            },
            "repo": {
                "type": "string",
                "description": "Repository name",
            },
        },
        "required": ["owner", "repo"],
    }
)
async def github_repo_info(owner: str, repo: str) -> str:
    """Get information about a GitHub repository"""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"token {APIS['github']['token']}",
            "Accept": "application/vnd.github.v3+json",
        }
        
        async with session.get(
            f"{APIS['github']['base_url']}/repos/{owner}/{repo}",
            headers=headers
        ) as response:
            data = await response.json()
            
            if response.status != 200:
                raise ValueError(f"GitHub API error: {data.get('message', 'Unknown error')}")
            
            info = {
                "name": data["name"],
                "description": data["description"],
                "stars": data["stargazers_count"],
                "forks": data["forks_count"],
                "open_issues": data["open_issues_count"],
                "language": data["language"],
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
            }
            
            return json.dumps(info, indent=2)

@mcp.tool(
    name="github_create_issue",
    description="Create an issue in a GitHub repository",
    parameters={
        "type": "object",
        "properties": {
            "owner": {
                "type": "string",
                "description": "Repository owner",
            },
            "repo": {
                "type": "string",
                "description": "Repository name",
            },
            "title": {
                "type": "string",
                "description": "Issue title",
            },
            "body": {
                "type": "string",
                "description": "Issue body",
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Issue labels",
            },
        },
        "required": ["owner", "repo", "title", "body"],
    }
)
async def github_create_issue(
    owner: str, repo: str, title: str, body: str, labels: Optional[List[str]] = None
) -> str:
    """Create an issue in a GitHub repository"""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"token {APIS['github']['token']}",
            "Accept": "application/vnd.github.v3+json",
        }
        
        data = {
            "title": title,
            "body": body,
        }
        if labels:
            data["labels"] = labels
        
        async with session.post(
            f"{APIS['github']['base_url']}/repos/{owner}/{repo}/issues",
            headers=headers,
            json=data
        ) as response:
            result = await response.json()
            
            if response.status != 201:
                raise ValueError(f"GitHub API error: {result.get('message', 'Unknown error')}")
            
            return f"Issue created: {result['html_url']}"

# Prompts for common API tasks
@mcp.prompt(
    name="weather_report",
    description="Generate a weather report for multiple cities",
    parameters=[
        {
            "name": "cities",
            "description": "Comma-separated list of cities",
            "required": True,
        },
    ]
)
async def weather_report_prompt(cities: str) -> str:
    """Generate weather report prompt"""
    city_list = [c.strip() for c in cities.split(",")]
    return f"""Please generate a comprehensive weather report for the following cities: {', '.join(city_list)}.

Use the get_weather tool for each city and create a summary that includes:
1. Current conditions for each city
2. Temperature comparisons
3. Any weather warnings or notable conditions
4. Recommendations for travelers"""

@mcp.prompt(
    name="github_activity",
    description="Analyze GitHub user activity",
    parameters=[
        {
            "name": "username",
            "description": "GitHub username",
            "required": True,
        },
    ]
)
async def github_activity_prompt(username: str) -> str:
    """Generate GitHub activity analysis prompt"""
    return f"""Please analyze the GitHub activity for user: {username}

Use the github_user_repos tool to get their repositories and provide:
1. Overview of their most popular repositories
2. Primary programming languages used
3. Recent activity summary
4. Interesting projects worth highlighting"""

# Start server
if __name__ == "__main__":
    # Check for required environment variables
    if not APIS["weather"]["api_key"]:
        print("Warning: OPENWEATHER_API_KEY not set", file=sys.stderr)
    if not APIS["github"]["token"]:
        print("Warning: GITHUB_TOKEN not set", file=sys.stderr)
    
    print("API Integration MCP server running", file=sys.stderr)
    mcp.run()
```

## Complete Client Examples

### 1. Interactive CLI Client

A command-line client that interacts with MCP servers.

```python
# cli_client.py
import asyncio
import json
import sys
import subprocess
from typing import Optional, List, Dict, Any
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from fastmcp.client import MCPClient

class InteractiveMCPClient:
    def __init__(self):
        self.client: Optional[MCPClient] = None
        self.connected = False
        self.resources = []
        self.tools = []
        self.prompts = []
        self.server_process = None
    
    async def connect(self, command: str, args: List[str]):
        """Connect to an MCP server"""
        try:
            # Start server process
            self.server_process = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Create client and connect
            self.client = MCPClient(
                name="interactive-cli",
                version="1.0.0"
            )
            
            await self.client.connect_stdio(self.server_process)
            self.connected = True
            
            # Cache available capabilities
            await self.refresh_capabilities()
            
            server_info = self.client.server_info
            print(f"Connected to server: {server_info.get('name', 'Unknown')}")
            print(f"Server version: {server_info.get('version', 'Unknown')}")
            
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.connected = False
            if self.server_process:
                self.server_process.terminate()
    
    async def refresh_capabilities(self):
        """Refresh cached capabilities"""
        try:
            # List resources
            result = await self.client.request("resources/list")
            self.resources = result.get("resources", [])
            
            # List tools
            result = await self.client.request("tools/list")
            self.tools = result.get("tools", [])
            
            # List prompts
            result = await self.client.request("prompts/list")
            self.prompts = result.get("prompts", [])
        except:
            # Server might not support all capabilities
            pass
    
    async def list_resources(self):
        """List available resources"""
        if not self.resources:
            print("No resources available")
            return
        
        print("\nAvailable Resources:")
        for i, resource in enumerate(self.resources, 1):
            print(f"{i}. {resource['name']} ({resource['uri']})")
            if resource.get('description'):
                print(f"   {resource['description']}")
    
    async def read_resource(self, uri: str):
        """Read a specific resource"""
        try:
            result = await self.client.request("resources/read", {"uri": uri})
            print(f"\nResource: {uri}")
            print("-" * 50)
            
            for item in result.get("contents", []):
                if item.get("text"):
                    print(item["text"])
                elif item.get("blob"):
                    print(f"[Binary data: {len(item['blob'])} bytes]")
        except Exception as e:
            print(f"Error reading resource: {e}")
    
    async def list_tools(self):
        """List available tools"""
        if not self.tools:
            print("No tools available")
            return
        
        print("\nAvailable Tools:")
        for i, tool in enumerate(self.tools, 1):
            print(f"{i}. {tool['name']}")
            if tool.get('description'):
                print(f"   {tool['description']}")
            if tool.get('inputSchema'):
                print(f"   Parameters: {json.dumps(tool['inputSchema'], indent=6)}")
    
    async def call_tool(self, name: str, args_str: str):
        """Call a tool with arguments"""
        try:
            # Parse arguments
            args = json.loads(args_str) if args_str else {}
            
            # Call tool
            result = await self.client.request(
                "tools/call",
                {"name": name, "arguments": args}
            )
            
            print(f"\nTool Result: {name}")
            print("-" * 50)
            
            for content in result.get("content", []):
                if content.get("type") == "text":
                    print(content["text"])
                elif content.get("type") == "image":
                    print(f"[Image data: {content.get('mimeType', 'unknown')}]")
            
            if result.get("isError"):
                print("(Error occurred during execution)")
                
        except json.JSONDecodeError:
            print("Invalid JSON arguments")
        except Exception as e:
            print(f"Error calling tool: {e}")
    
    async def list_prompts(self):
        """List available prompts"""
        if not self.prompts:
            print("No prompts available")
            return
        
        print("\nAvailable Prompts:")
        for i, prompt_info in enumerate(self.prompts, 1):
            print(f"{i}. {prompt_info['name']}")
            if prompt_info.get('description'):
                print(f"   {prompt_info['description']}")
            if prompt_info.get('arguments'):
                for arg in prompt_info['arguments']:
                    req = " (required)" if arg.get('required') else ""
                    print(f"   - {arg['name']}: {arg.get('description', '')}{req}")
    
    async def get_prompt(self, name: str, args_str: str):
        """Get a prompt with arguments"""
        try:
            # Parse arguments
            args = json.loads(args_str) if args_str else {}
            
            # Get prompt
            result = await self.client.request(
                "prompts/get",
                {"name": name, "arguments": args}
            )
            
            print(f"\nPrompt: {name}")
            if result.get('description'):
                print(f"Description: {result['description']}")
            print("-" * 50)
            
            for message in result.get('messages', []):
                role = message.get('role', 'unknown')
                print(f"\n[{role}]:")
                content = message.get('content', {})
                if isinstance(content, dict) and content.get('text'):
                    print(content['text'])
                elif isinstance(content, str):
                    print(content)
                    
        except json.JSONDecodeError:
            print("Invalid JSON arguments")
        except Exception as e:
            print(f"Error getting prompt: {e}")
    
    async def interactive_loop(self):
        """Main interactive loop"""
        # Command completer
        commands = [
            "help", "connect", "disconnect", "resources", "read",
            "tools", "call", "prompts", "prompt", "refresh", "exit"
        ]
        completer = WordCompleter(commands)
        
        print("MCP Interactive Client")
        print("Type 'help' for available commands")
        
        while True:
            try:
                # Get user input
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: prompt("mcp> ", completer=completer)
                )
                
                if not user_input.strip():
                    continue
                
                # Parse command
                parts = user_input.strip().split(maxsplit=2)
                command = parts[0].lower()
                
                # Execute command
                if command == "help":
                    self.show_help()
                
                elif command == "connect":
                    if len(parts) < 2:
                        print("Usage: connect <command> [args...]")
                    else:
                        cmd = parts[1]
                        args = parts[2].split() if len(parts) > 2 else []
                        await self.connect(cmd, args)
                
                elif command == "disconnect":
                    if self.connected and self.client:
                        await self.client.disconnect()
                        self.connected = False
                        if self.server_process:
                            self.server_process.terminate()
                            self.server_process = None
                        print("Disconnected")
                    else:
                        print("Not connected")
                
                elif command == "resources":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.list_resources()
                
                elif command == "read":
                    if not self.connected:
                        print("Not connected to a server")
                    elif len(parts) < 2:
                        print("Usage: read <resource-uri>")
                    else:
                        await self.read_resource(parts[1])
                
                elif command == "tools":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.list_tools()
                
                elif command == "call":
                    if not self.connected:
                        print("Not connected to a server")
                    elif len(parts) < 2:
                        print("Usage: call <tool-name> [json-args]")
                    else:
                        tool_name = parts[1]
                        args = parts[2] if len(parts) > 2 else ""
                        await self.call_tool(tool_name, args)
                
                elif command == "prompts":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.list_prompts()
                
                elif command == "prompt":
                    if not self.connected:
                        print("Not connected to a server")
                    elif len(parts) < 2:
                        print("Usage: prompt <prompt-name> [json-args]")
                    else:
                        prompt_name = parts[1]
                        args = parts[2] if len(parts) > 2 else ""
                        await self.get_prompt(prompt_name, args)
                
                elif command == "refresh":
                    if not self.connected:
                        print("Not connected to a server")
                    else:
                        await self.refresh_capabilities()
                        print("Capabilities refreshed")
                
                elif command == "exit":
                    if self.connected and self.client:
                        await self.client.disconnect()
                    if self.server_process:
                        self.server_process.terminate()
                    print("Goodbye!")
                    break
                
                else:
                    print(f"Unknown command: {command}")
                    print("Type 'help' for available commands")
                    
            except KeyboardInterrupt:
                print("\nUse 'exit' to quit")
            except Exception as e:
                print(f"Error: {e}")
    
    def show_help(self):
        """Show help information"""
        help_text = """
Available Commands:
  connect <command> [args...]  - Connect to an MCP server
  disconnect                   - Disconnect from server
  resources                    - List available resources
  read <uri>                   - Read a resource
  tools                        - List available tools
  call <tool> [json-args]      - Call a tool
  prompts                      - List available prompts
  prompt <name> [json-args]    - Get a prompt
  refresh                      - Refresh server capabilities
  exit                         - Exit the client
  help                         - Show this help

Examples:
  connect python server.py
  connect node ./server.js --debug
  read file:///path/to/file.txt
  call create_file '{"path": "/tmp/test.txt", "content": "Hello"}'
  prompt weather_report '{"cities": "London, Paris, Berlin"}'
"""
        print(help_text)

async def main():
    client = InteractiveMCPClient()
    
    # Connect to server if provided as command line argument
    if len(sys.argv) > 1:
        await client.connect(sys.argv[1], sys.argv[2:])
    
    # Run interactive loop
    await client.interactive_loop()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Web Dashboard Client

A web-based client with a dashboard interface.

```typescript
// web-client/src/MCPDashboard.tsx
import React, { useState, useEffect } from 'react';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { WebSocketClientTransport } from '@modelcontextprotocol/sdk/client/websocket.js';

interface Resource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

interface Tool {
  name: string;
  description?: string;
  inputSchema?: any;
}

interface ServerInfo {
  name: string;
  version: string;
  capabilities: any;
}

const MCPDashboard: React.FC = () => {
  const [client, setClient] = useState<Client | null>(null);
  const [connected, setConnected] = useState(false);
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [selectedResource, setSelectedResource] = useState<string | null>(null);
  const [resourceContent, setResourceContent] = useState<string>('');
  const [selectedTool, setSelectedTool] = useState<string | null>(null);
  const [toolArgs, setToolArgs] = useState<string>('{}');
  const [toolResult, setToolResult] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');

  // Connect to MCP server
  const connect = async (url: string) => {
    try {
      setLoading(true);
      setError('');
      
      const newClient = new Client({
        name: 'web-dashboard',
        version: '1.0.0',
      });
      
      const transport = new WebSocketClientTransport(url);
      await newClient.connect(transport);
      
      setClient(newClient);
      setConnected(true);
      
      // Get server info
      const info = newClient.serverInfo;
      setServerInfo(info);
      
      // Load initial data
      await loadCapabilities(newClient);
      
    } catch (err) {
      setError(`Connection failed: ${err.message}`);
      setConnected(false);
    } finally {
      setLoading(false);
    }
  };

  // Load server capabilities
  const loadCapabilities = async (client: Client) => {
    try {
      // Load resources
      const resourceList = await client.request('resources/list');
      setResources(resourceList.resources || []);
      
      // Load tools
      const toolList = await client.request('tools/list');
      setTools(toolList.tools || []);
      
    } catch (err) {
      console.error('Failed to load capabilities:', err);
    }
  };

  // Read a resource
  const readResource = async (uri: string) => {
    if (!client) return;
    
    try {
      setLoading(true);
      setError('');
      
      const content = await client.request('resources/read', { uri });
      const text = content.contents?.[0]?.text || '';
      setResourceContent(text);
      
    } catch (err) {
      setError(`Failed to read resource: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Call a tool
  const callTool = async () => {
    if (!client || !selectedTool) return;
    
    try {
      setLoading(true);
      setError('');
      setToolResult('');
      
      const args = JSON.parse(toolArgs);
      const result = await client.request('tools/call', {
        name: selectedTool,
        arguments: args,
      });
      
      const text = result.content?.[0]?.text || JSON.stringify(result);
      setToolResult(text);
      
    } catch (err) {
      setError(`Tool execution failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mcp-dashboard">
      <header>
        <h1>MCP Dashboard</h1>
        {connected ? (
          <div className="server-info">
            <span className="status connected">● Connected</span>
            <span>{serverInfo?.name} v{serverInfo?.version}</span>
          </div>
        ) : (
          <div className="connection-form">
            <input
              type="text"
              placeholder="ws://localhost:3000"
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  connect(e.currentTarget.value);
                }
              }}
            />
            <button onClick={(e) => {
              const input = e.currentTarget.previousSibling as HTMLInputElement;
              connect(input.value);
            }}>
              Connect
            </button>
          </div>
        )}
      </header>

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      {connected && (
        <div className="dashboard-content">
          <div className="panel resources-panel">
            <h2>Resources</h2>
            <div className="resource-list">
              {resources.map((resource) => (
                <div
                  key={resource.uri}
                  className={`resource-item ${selectedResource === resource.uri ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedResource(resource.uri);
                    readResource(resource.uri);
                  }}
                >
                  <div className="resource-name">{resource.name}</div>
                  <div className="resource-uri">{resource.uri}</div>
                  {resource.description && (
                    <div className="resource-desc">{resource.description}</div>
                  )}
                </div>
              ))}
            </div>
            
            {selectedResource && (
              <div className="resource-content">
                <h3>Content</h3>
                <pre>{resourceContent}</pre>
              </div>
            )}
          </div>

          <div className="panel tools-panel">
            <h2>Tools</h2>
            <div className="tool-list">
              {tools.map((tool) => (
                <div
                  key={tool.name}
                  className={`tool-item ${selectedTool === tool.name ? 'selected' : ''}`}
                  onClick={() => {
                    setSelectedTool(tool.name);
                    setToolArgs(JSON.stringify(
                      tool.inputSchema?.properties ? 
                        Object.fromEntries(
                          Object.entries(tool.inputSchema.properties).map(
                            ([key, schema]: [string, any]) => [key, schema.example || '']
                          )
                        ) : {},
                      null,
                      2
                    ));
                  }}
                >
                  <div className="tool-name">{tool.name}</div>
                  {tool.description && (
                    <div className="tool-desc">{tool.description}</div>
                  )}
                </div>
              ))}
            </div>
            
            {selectedTool && (
              <div className="tool-execution">
                <h3>Execute: {selectedTool}</h3>
                <div className="tool-args">
                  <label>Arguments (JSON):</label>
                  <textarea
                    value={toolArgs}
                    onChange={(e) => setToolArgs(e.target.value)}
                    rows={10}
                  />
                </div>
                <button 
                  onClick={callTool}
                  disabled={loading}
                >
                  {loading ? 'Executing...' : 'Execute Tool'}
                </button>
                
                {toolResult && (
                  <div className="tool-result">
                    <h4>Result</h4>
                    <pre>{toolResult}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// Styles
const styles = `
.mcp-dashboard {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 1px solid #e0e0e0;
}

h1 {
  margin: 0;
  font-size: 28px;
}

.server-info {
  display: flex;
  align-items: center;
  gap: 15px;
}

.status {
  display: flex;
  align-items: center;
  gap: 5px;
}

.status.connected {
  color: #4caf50;
}

.connection-form {
  display: flex;
  gap: 10px;
}

.connection-form input {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  width: 250px;
}

.connection-form button {
  padding: 8px 16px;
  background: #2196f3;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.error-banner {
  background: #f44336;
  color: white;
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 20px;
}

.dashboard-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.panel {
  background: #f5f5f5;
  border-radius: 8px;
  padding: 20px;
}

.panel h2 {
  margin-top: 0;
  margin-bottom: 15px;
  font-size: 20px;
}

.resource-list,
.tool-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.resource-item,
.tool-item {
  background: white;
  padding: 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.resource-item:hover,
.tool-item:hover {
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.resource-item.selected,
.tool-item.selected {
  border: 2px solid #2196f3;
}

.resource-name,
.tool-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.resource-uri {
  font-size: 12px;
  color: #666;
  font-family: monospace;
}

.resource-desc,
.tool-desc {
  font-size: 14px;
  color: #666;
  margin-top: 4px;
}

.resource-content,
.tool-execution {
  background: white;
  padding: 15px;
  border-radius: 4px;
}

.resource-content h3,
.tool-execution h3 {
  margin-top: 0;
  margin-bottom: 10px;
}

pre {
  background: #f0f0f0;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.tool-args {
  margin-bottom: 15px;
}

.tool-args label {
  display: block;
  margin-bottom: 5px;
  font-weight: 600;
}

.tool-args textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-family: monospace;
  font-size: 13px;
}

.tool-execution button {
  padding: 10px 20px;
  background: #4caf50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
}

.tool-execution button:disabled {
  background: #cccccc;
  cursor: not-allowed;
}

.tool-result {
  margin-top: 20px;
}

.tool-result h4 {
  margin-bottom: 10px;
}
`;

export default MCPDashboard;
```

## Real-World Implementations

### 1. Claude Desktop Configuration

Example configuration for Claude Desktop with multiple MCP servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "python",
      "args": ["/path/to/filesystem_server.py"],
      "env": {
        "ALLOWED_DIRECTORIES": "/Users/username/Documents,/Users/username/Desktop"
      }
    },
    "github": {
      "command": "python",
      "args": ["/path/to/github_server.py"],
      "env": {
        "GITHUB_TOKEN": "your-github-token"
      }
    },
    "database": {
      "command": "python",
      "args": ["/path/to/database_server.py"],
      "env": {
        "DATABASE_URL": "postgresql://localhost/mydb"
      }
    },
    "api-integration": {
      "command": "python",
      "args": ["/path/to/api_server.py"],
      "env": {
        "OPENWEATHER_API_KEY": "${OPENWEATHER_API_KEY}",
        "GITHUB_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "docker-compose": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e", "MCP_ENV=production",
        "mcp/server:latest"
      ]
    }
  }
}
```

### 2. VS Code Extension Integration

Example VS Code extension that integrates MCP:

```typescript
// extension.ts
import * as vscode from 'vscode';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

export function activate(context: vscode.ExtensionContext) {
  let mcpClient: Client | null = null;
  
  // Register MCP connection command
  const connectCommand = vscode.commands.registerCommand(
    'mcp.connect',
    async () => {
      const serverPath = await vscode.window.showInputBox({
        prompt: 'Enter MCP server command',
        placeHolder: 'node /path/to/server.js',
      });
      
      if (!serverPath) return;
      
      try {
        mcpClient = new Client({
          name: 'vscode-mcp',
          version: '1.0.0',
        });
        
        const [command, ...args] = serverPath.split(' ');
        const transport = new StdioClientTransport({ command, args });
        
        await mcpClient.connect(transport);
        
        vscode.window.showInformationMessage(
          `Connected to MCP server: ${mcpClient.serverInfo.name}`
        );
        
        // Register additional commands
        registerMCPCommands(context, mcpClient);
        
      } catch (error) {
        vscode.window.showErrorMessage(
          `Failed to connect: ${error.message}`
        );
      }
    }
  );
  
  context.subscriptions.push(connectCommand);
}

function registerMCPCommands(
  context: vscode.ExtensionContext,
  client: Client
) {
  // List resources command
  const listResourcesCommand = vscode.commands.registerCommand(
    'mcp.listResources',
    async () => {
      const resources = await client.request('resources/list');
      
      const items = resources.resources.map(r => ({
        label: r.name,
        description: r.uri,
        detail: r.description,
        resource: r,
      }));
      
      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'Select a resource to read',
      });
      
      if (selected) {
        const content = await client.request('resources/read', {
          uri: selected.resource.uri,
        });
        
        // Open in new editor
        const doc = await vscode.workspace.openTextDocument({
          content: content.contents[0].text,
          language: getLanguageId(selected.resource.mimeType),
        });
        
        vscode.window.showTextDocument(doc);
      }
    }
  );
  
  // Execute tool command
  const executeToolCommand = vscode.commands.registerCommand(
    'mcp.executeTool',
    async () => {
      const tools = await client.request('tools/list');
      
      const items = tools.tools.map(t => ({
        label: t.name,
        detail: t.description,
        tool: t,
      }));
      
      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'Select a tool to execute',
      });
      
      if (selected) {
        // Get tool arguments
        const argsStr = await vscode.window.showInputBox({
          prompt: `Enter arguments for ${selected.tool.name} (JSON)`,
          placeHolder: '{}',
          value: '{}',
        });
        
        if (argsStr) {
          try {
            const args = JSON.parse(argsStr);
            const result = await client.request('tools/call', {
              name: selected.tool.name,
              arguments: args,
            });
            
            // Show result
            const output = vscode.window.createOutputChannel('MCP Tool Result');
            output.appendLine(`Tool: ${selected.tool.name}`);
            output.appendLine('-'.repeat(50));
            output.appendLine(result.content[0].text);
            output.show();
            
          } catch (error) {
            vscode.window.showErrorMessage(
              `Tool execution failed: ${error.message}`
            );
          }
        }
      }
    }
  );
  
  context.subscriptions.push(listResourcesCommand, executeToolCommand);
}

function getLanguageId(mimeType: string): string {
  const mappings = {
    'text/javascript': 'javascript',
    'text/typescript': 'typescript',
    'text/x-python': 'python',
    'text/markdown': 'markdown',
    'application/json': 'json',
    'text/html': 'html',
    'text/css': 'css',
  };
  return mappings[mimeType] || 'plaintext';
}
```

## Integration Examples

### 1. LangChain Integration

Integrating MCP with LangChain for enhanced AI applications:

```python
# langchain_mcp_integration.py
from langchain.tools import BaseTool
from langchain.agents import initialize_agent, AgentType
from langchain.llms import OpenAI
from fastmcp.client import MCPClient
import asyncio
import json
import subprocess
from typing import Optional, Type, Dict, Any
from pydantic import BaseModel, Field

class MCPToolInput(BaseModel):
    """Input schema for MCP tool"""
    tool_name: str = Field(description="Name of the MCP tool to call")
    arguments: str = Field(description="JSON string of tool arguments")

class MCPTool(BaseTool):
    """LangChain tool that wraps MCP tools"""
    name = "mcp_tool"
    description = "Execute tools from an MCP server"
    args_schema: Type[BaseModel] = MCPToolInput
    mcp_client: Optional[MCPClient] = None
    
    def __init__(self, mcp_client: MCPClient):
        super().__init__()
        self.mcp_client = mcp_client
    
    def _run(self, tool_name: str, arguments: str) -> str:
        """Execute MCP tool synchronously"""
        return asyncio.run(self._arun(tool_name, arguments))
    
    async def _arun(self, tool_name: str, arguments: str) -> str:
        """Execute MCP tool asynchronously"""
        try:
            args = json.loads(arguments)
            result = await self.mcp_client.request(
                "tools/call",
                {"name": tool_name, "arguments": args}
            )
            
            # Extract text content
            text_content = []
            for content in result.get("content", []):
                if content.get("type") == "text":
                    text_content.append(content["text"])
            
            return "\n".join(text_content)
            
        except Exception as e:
            return f"Error executing MCP tool: {str(e)}"

class MCPResourceTool(BaseTool):
    """LangChain tool for reading MCP resources"""
    name = "mcp_resource"
    description = "Read resources from an MCP server"
    mcp_client: Optional[MCPClient] = None
    
    def __init__(self, mcp_client: MCPClient):
        super().__init__()
        self.mcp_client = mcp_client
    
    def _run(self, uri: str) -> str:
        """Read MCP resource synchronously"""
        return asyncio.run(self._arun(uri))
    
    async def _arun(self, uri: str) -> str:
        """Read MCP resource asynchronously"""
        try:
            result = await self.mcp_client.request(
                "resources/read",
                {"uri": uri}
            )
            
            # Extract text content
            text_content = []
            for item in result.get("contents", []):
                if item.get("text"):
                    text_content.append(item["text"])
            
            return "\n".join(text_content)
            
        except Exception as e:
            return f"Error reading MCP resource: {str(e)}"

async def create_mcp_agent():
    """Create a LangChain agent with MCP tools"""
    # Start MCP server process
    server_process = subprocess.Popen(
        ["python", "mcp_server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Connect to MCP server
    client = MCPClient(name="langchain-mcp", version="1.0.0")
    await client.connect_stdio(server_process)
    
    # Get available tools and resources
    tools_result = await client.request("tools/list")
    resources_result = await client.request("resources/list")
    
    tools_list = tools_result.get("tools", [])
    resources_list = resources_result.get("resources", [])
    
    # Create tool descriptions
    tool_descriptions = []
    for tool in tools_list:
        desc = f"- {tool['name']}: {tool.get('description', '')}"
        if tool.get('inputSchema'):
            desc += f" (args: {json.dumps(tool['inputSchema'])})"
        tool_descriptions.append(desc)
    
    resource_descriptions = []
    for resource in resources_list:
        desc = f"- {resource['uri']}: {resource['name']}"
        resource_descriptions.append(desc)
    
    # Update tool descriptions
    MCPTool.description = f"""Execute tools from MCP server.
Available tools:
{chr(10).join(tool_descriptions)}

To use: provide tool_name and arguments as JSON string."""
    
    MCPResourceTool.description = f"""Read resources from MCP server.
Available resources:
{chr(10).join(resource_descriptions)}

To use: provide the resource URI."""
    
    # Create LangChain tools
    mcp_tool = MCPTool(mcp_client=client)
    mcp_resource = MCPResourceTool(mcp_client=client)
    
    # Initialize LLM and agent
    llm = OpenAI(temperature=0)
    tools = [mcp_tool, mcp_resource]
    
    agent = initialize_agent(
        tools,
        llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True
    )
    
    return agent, client, server_process

# Example usage
async def main():
    agent, mcp_client, server_process = await create_mcp_agent()
    
    try:
        # Example queries
        queries = [
            "What files are available in the resources?",
            "Read the configuration file and summarize its contents",
            "Use the weather tool to get the current weather in London",
            "Create a new file called test.txt with the content 'Hello from LangChain'"
        ]
        
        for query in queries:
            print(f"\nQuery: {query}")
            print("-" * 50)
            response = agent.run(query)
            print(f"Response: {response}")
    
    finally:
        # Cleanup
        await mcp_client.disconnect()
        server_process.terminate()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Jupyter Notebook Integration

MCP integration for Jupyter notebooks:

```python
# mcp_jupyter.py
import asyncio
import json
import subprocess
from typing import Optional, List, Dict, Any
from IPython.display import display, HTML, JSON
from ipywidgets import widgets, Layout
from fastmcp.client import MCPClient

class MCPJupyterClient:
    """MCP client for Jupyter notebooks with interactive widgets"""
    
    def __init__(self):
        self.client: Optional[MCPClient] = None
        self.server_process: Optional[subprocess.Popen] = None
        self.connected = False
        self.setup_ui()
    
    def setup_ui(self):
        """Create interactive UI widgets"""
        # Connection widgets
        self.server_input = widgets.Text(
            placeholder='python server.py',
            description='Server:',
            layout=Layout(width='400px')
        )
        
        self.connect_button = widgets.Button(
            description='Connect',
            button_style='primary'
        )
        self.connect_button.on_click(self.on_connect_click)
        
        self.status_label = widgets.Label('Not connected')
        
        # Resource browser
        self.resource_dropdown = widgets.Dropdown(
            options=[],
            description='Resource:',
            layout=Layout(width='400px')
        )
        
        self.read_button = widgets.Button(
            description='Read Resource',
            button_style='info',
            disabled=True
        )
        self.read_button.on_click(self.on_read_click)
        
        # Tool executor
        self.tool_dropdown = widgets.Dropdown(
            options=[],
            description='Tool:',
            layout=Layout(width='400px')
        )
        
        self.args_textarea = widgets.Textarea(
            placeholder='{}',
            description='Arguments:',
            layout=Layout(width='400px', height='100px')
        )
        
        self.execute_button = widgets.Button(
            description='Execute Tool',
            button_style='success',
            disabled=True
        )
        self.execute_button.on_click(self.on_execute_click)
        
        # Output area
        self.output = widgets.Output()
        
        # Layout
        self.ui = widgets.VBox([
            widgets.HBox([self.server_input, self.connect_button, self.status_label]),
            widgets.HTML('<hr>'),
            widgets.HTML('<h3>Resources</h3>'),
            widgets.HBox([self.resource_dropdown, self.read_button]),
            widgets.HTML('<h3>Tools</h3>'),
            widgets.VBox([self.tool_dropdown, self.args_textarea, self.execute_button]),
            widgets.HTML('<hr>'),
            self.output
        ])
    
    def display(self):
        """Display the UI"""
        display(self.ui)
    
    def on_connect_click(self, _):
        """Handle connect button click"""
        asyncio.create_task(self.connect())
    
    async def connect(self):
        """Connect to MCP server"""
        server_cmd = self.server_input.value.strip()
        if not server_cmd:
            return
        
        with self.output:
            try:
                self.status_label.value = 'Connecting...'
                
                # Parse command
                parts = server_cmd.split()
                command = parts[0]
                args = parts[1:] if len(parts) > 1 else []
                
                # Start server process
                self.server_process = subprocess.Popen(
                    [command] + args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                # Create and connect client
                self.client = MCPClient(
                    name="jupyter-mcp",
                    version="1.0.0"
                )
                await self.client.connect_stdio(self.server_process)
                
                self.connected = True
                server_info = self.client.server_info
                self.status_label.value = f'Connected to {server_info.get("name", "Unknown")}'
                
                # Load capabilities
                await self.load_capabilities()
                
                # Enable buttons
                self.read_button.disabled = False
                self.execute_button.disabled = False
                
            except Exception as e:
                self.status_label.value = f'Error: {str(e)}'
                self.connected = False
                if self.server_process:
                    self.server_process.terminate()
                    self.server_process = None
    
    async def load_capabilities(self):
        """Load server capabilities"""
        # Load resources
        result = await self.client.request("resources/list")
        resources = result.get("resources", [])
        self.resource_dropdown.options = [
            (f"{r['name']} ({r['uri']})", r['uri'])
            for r in resources
        ]
        
        # Load tools  
        result = await self.client.request("tools/list")
        tools = result.get("tools", [])
        self.tool_dropdown.options = [
            (f"{t['name']} - {t.get('description', '')}", t['name'])
            for t in tools
        ]
        
        # Store tool schemas
        self.tool_schemas = {t['name']: t for t in tools}
    
    def on_read_click(self, _):
        """Handle read resource button click"""
        asyncio.create_task(self.read_resource())
    
    async def read_resource(self):
        """Read selected resource"""
        if not self.connected:
            return
        
        uri = self.resource_dropdown.value
        if not uri:
            return
        
        with self.output:
            try:
                result = await self.client.request(
                    "resources/read",
                    {"uri": uri}
                )
                
                # Display content
                for item in result.get("contents", []):
                    if item.get("text"):
                        # Try to parse as JSON for pretty display
                        try:
                            data = json.loads(item["text"])
                            display(JSON(data))
                        except:
                            print(item["text"])
                    elif item.get("blob"):
                        print(f"[Binary data: {len(item['blob'])} bytes]")
                        
            except Exception as e:
                print(f"Error reading resource: {e}")
    
    def on_execute_click(self, _):
        """Handle execute tool button click"""
        asyncio.create_task(self.execute_tool())
    
    async def execute_tool(self):
        """Execute selected tool"""
        if not self.connected:
            return
        
        tool_name = self.tool_dropdown.value
        if not tool_name:
            return
        
        with self.output:
            try:
                # Parse arguments
                args_str = self.args_textarea.value.strip() or '{}'
                args = json.loads(args_str)
                
                # Show tool schema if empty args
                if args == {} and tool_name in self.tool_schemas:
                    schema = self.tool_schemas[tool_name]
                    if schema.get('inputSchema'):
                        print("Tool schema:")
                        display(JSON(schema['inputSchema']))
                        print("\nExecuting with empty arguments...")
                
                # Execute tool
                result = await self.client.request(
                    "tools/call",
                    {"name": tool_name, "arguments": args}
                )
                
                # Display result
                print(f"\nTool result for '{tool_name}':")
                for content in result.get("content", []):
                    if content.get("type") == "text":
                        # Try to parse as JSON for pretty display
                        try:
                            data = json.loads(content["text"])
                            display(JSON(data))
                        except:
                            print(content["text"])
                    elif content.get("type") == "image":
                        # Image data
                        display(HTML(f'<img src="data:{content.get("mimeType", "")};base64,{content.get("data", "")}">'))
                
                if result.get("isError"):
                    print("(Error occurred during execution)")
                    
            except json.JSONDecodeError:
                print("Error: Invalid JSON in arguments")
            except Exception as e:
                print(f"Error executing tool: {e}")
    
    def query(self, question: str):
        """Helper method for quick queries"""
        if not self.connected:
            print("Not connected to MCP server")
            return
        
        # This could be extended to use an LLM to interpret the question
        # and automatically call the right tools/resources
        with self.output:
            print(f"Query: {question}")
            print("(Manual tool/resource selection required)")
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        if self.server_process:
            self.server_process.terminate()

# Usage in Jupyter notebook:
# client = MCPJupyterClient()
# client.display()
```

## Advanced Patterns

### 1. Server Composition

Composing multiple MCP servers into a unified interface:

```python
# server_composer.py
import asyncio
import json
import subprocess
import sys
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from mcp.server.fastmcp import FastMCP
from fastmcp.client import MCPClient

@dataclass
class ServerConfig:
    """Configuration for an upstream MCP server"""
    name: str
    command: str
    args: List[str]
    prefix: str

class ComposedMCPServer:
    """Compose multiple MCP servers into a unified interface"""
    
    def __init__(self, configs: List[ServerConfig]):
        self.configs = configs
        self.clients: Dict[str, MCPClient] = {}
        self.processes: Dict[str, subprocess.Popen] = {}
        
        # Create composed server
        self.mcp = FastMCP(
            name="composed-server",
            version="1.0.0"
        )
        
        self.setup_handlers()
    
    async def start(self):
        """Start all upstream servers and connect clients"""
        for config in self.configs:
            # Start server process
            process = subprocess.Popen(
                [config.command] + config.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.processes[config.name] = process
            
            # Create and connect client
            client = MCPClient(
                name=f"composer-{config.name}",
                version="1.0.0"
            )
            await client.connect_stdio(process)
            self.clients[config.name] = client
        
        print(f"Connected to {len(self.clients)} upstream servers", file=sys.stderr)
  
    def setup_handlers(self):
        """Setup handlers for the composed server"""
        
        @self.mcp.list_resources()
        async def list_all_resources() -> List[Dict[str, Any]]:
            """List resources from all servers"""
            all_resources = []
            
            for config in self.configs:
                client = self.clients.get(config.name)
                if not client:
                    continue
                
                try:
                    response = await client.request("resources/list")
                    resources = response.get("resources", [])
                    
                    # Prefix resource URIs
                    for resource in resources:
                        all_resources.append({
                            "uri": f"{config.prefix}:{resource['uri']}",
                            "name": f"[{config.name}] {resource['name']}",
                            "mimeType": resource.get("mimeType", "text/plain"),
                            "description": resource.get("description"),
                        })
                except Exception as e:
                    print(f"Failed to list resources from {config.name}: {e}", file=sys.stderr)
            
            return all_resources
        
        @self.mcp.resource("*:*")
        async def read_prefixed_resource(uri: str) -> str:
            """Read resources from appropriate server"""
            # Parse prefixed URI
            parts = uri.split(":", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid URI format: {uri}")
            
            prefix, actual_uri = parts
            config = next((c for c in self.configs if c.prefix == prefix), None)
            if not config:
                raise ValueError(f"Unknown prefix: {prefix}")
            
            client = self.clients.get(config.name)
            if not client:
                raise ValueError(f"Server {config.name} not connected")
            
            # Request from upstream server
            response = await client.request("resources/read", {"uri": actual_uri})
            
            # Extract text content
            contents = response.get("contents", [])
            if contents and contents[0].get("text"):
                return contents[0]["text"]
            return ""
    
        @self.mcp.list_tools()
        async def list_all_tools() -> List[Dict[str, Any]]:
            """List tools from all servers"""
            all_tools = []
            
            for config in self.configs:
                client = self.clients.get(config.name)
                if not client:
                    continue
                
                try:
                    response = await client.request("tools/list")
                    tools = response.get("tools", [])
                    
                    # Prefix tool names
                    for tool in tools:
                        all_tools.append({
                            "name": f"{config.prefix}_{tool['name']}",
                            "description": f"[{config.name}] {tool.get('description', '')}",
                            "inputSchema": tool.get("inputSchema", {}),
                        })
                except Exception as e:
                    print(f"Failed to list tools from {config.name}: {e}", file=sys.stderr)
            
            return all_tools
        
        # Dynamic tool handler for all prefixed tools
        @self.mcp.tool_handler()
        async def handle_prefixed_tool(name: str, arguments: Dict[str, Any]) -> str:
            """Execute tools on appropriate server"""
            # Parse prefixed tool name
            parts = name.split("_", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid tool name format: {name}")
            
            prefix, actual_name = parts
            config = next((c for c in self.configs if c.prefix == prefix), None)
            if not config:
                raise ValueError(f"Unknown prefix: {prefix}")
            
            client = self.clients.get(config.name)
            if not client:
                raise ValueError(f"Server {config.name} not connected")
            
            # Call tool on upstream server
            response = await client.request(
                "tools/call",
                {"name": actual_name, "arguments": arguments}
            )
            
            # Extract text content
            content = response.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0]["text"]
            return json.dumps(response)
    
    async def run(self):
        """Run the composed server"""
        await self.start()
        self.mcp.run()
    
    def cleanup(self):
        """Cleanup all connections and processes"""
        for client in self.clients.values():
            asyncio.create_task(client.disconnect())
        
        for process in self.processes.values():
            process.terminate()

# Usage
if __name__ == "__main__":
    configs = [
        ServerConfig(
            name="filesystem",
            command="python",
            args=["filesystem_server.py"],
            prefix="fs"
        ),
        ServerConfig(
            name="database",
            command="python",
            args=["database_server.py"],
            prefix="db"
        ),
        ServerConfig(
            name="api",
            command="python",
            args=["api_server.py"],
            prefix="api"
        ),
    ]
    
    composer = ComposedMCPServer(configs)
    
    try:
        print("Starting composed MCP server...", file=sys.stderr)
        asyncio.run(composer.run())
    except KeyboardInterrupt:
        print("\nShutting down...", file=sys.stderr)
        composer.cleanup()
```

### 2. Middleware System

Advanced middleware system for MCP servers:

```python
# middleware_system.py
import time
import json
import asyncio
from typing import Dict, Any, Callable, List, Optional, Awaitable
from datetime import datetime
from functools import wraps
from mcp.server.fastmcp import FastMCP

# Type definitions
RequestHandler = Callable[[Dict[str, Any]], Awaitable[Any]]
Middleware = Callable[[Dict[str, Any], RequestHandler], Awaitable[Any]]

class MiddlewareMCP(FastMCP):
    """FastMCP with middleware support"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.middlewares: Dict[str, List[Middleware]] = {}
    
    def use(self, methods: str | List[str], middleware: Middleware):
        """Add middleware for specific methods"""
        if isinstance(methods, str):
            methods = [methods]
        
        for method in methods:
            if method not in self.middlewares:
                self.middlewares[method] = []
            self.middlewares[method].append(middleware)
    
    def apply_middleware(self, method: str, handler: RequestHandler) -> RequestHandler:
        """Apply middleware chain to a handler"""
        @wraps(handler)
        async def wrapped_handler(request: Dict[str, Any]) -> Any:
            middlewares = self.middlewares.get(method, [])
            
            # Build middleware chain
            async def execute_chain(index: int, req: Dict[str, Any]) -> Any:
                if index >= len(middlewares):
                    return await handler(req)
                
                middleware = middlewares[index]
                return await middleware(
                    req,
                    lambda r: execute_chain(index + 1, r)
                )
            
            return await execute_chain(0, request)
        
        return wrapped_handler

# Example middlewares

# Logging middleware
async def logging_middleware(request: Dict[str, Any], next: RequestHandler) -> Any:
    """Log all requests and responses"""
    start_time = time.time()
    method = request.get('method', 'unknown')
    timestamp = datetime.now().isoformat()
    
    print(f"[{timestamp}] {method} - Start")
    
    try:
        result = await next(request)
        duration = (time.time() - start_time) * 1000  # ms
        print(f"[{timestamp}] {method} - Success ({duration:.2f}ms)")
        return result
    except Exception as error:
        duration = (time.time() - start_time) * 1000  # ms
        print(f"[{timestamp}] {method} - Error ({duration:.2f}ms): {error}")
        raise

# Rate limiting middleware
class RateLimiter:
    """Rate limiting middleware"""
    
    def __init__(self, window_seconds: float, max_requests: int):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.requests: Dict[str, List[float]] = {}
    
    async def middleware(self, request: Dict[str, Any], next: RequestHandler) -> Any:
        """Check rate limit before processing request"""
        method = request.get('method', 'unknown')
        now = time.time()
        
        # Get request timestamps
        timestamps = self.requests.get(method, [])
        
        # Remove old timestamps
        valid_timestamps = [
            t for t in timestamps 
            if now - t < self.window_seconds
        ]
        
        # Check rate limit
        if len(valid_timestamps) >= self.max_requests:
            raise ValueError(
                f"Rate limit exceeded for {method}. "
                f"Max {self.max_requests} requests per {self.window_seconds}s"
            )
        
        # Add current timestamp
        valid_timestamps.append(now)
        self.requests[method] = valid_timestamps
        
        return await next(request)

# Caching middleware
class CacheMiddleware:
    """Simple caching middleware"""
    
    def __init__(self, ttl_seconds: float):
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}
    
    async def middleware(self, request: Dict[str, Any], next: RequestHandler) -> Any:
        """Cache read operations"""
        method = request.get('method', '')
        
        # Only cache read operations
        if 'read' not in method and 'list' not in method:
            return await next(request)
        
        # Create cache key
        cache_key = json.dumps({
            'method': method,
            'params': request.get('params', {})
        }, sort_keys=True)
        
        # Check cache
        cached = self.cache.get(cache_key)
        if cached and cached['expires'] > time.time():
            print(f"Cache hit for {method}")
            return cached['data']
        
        # Execute request
        result = await next(request)
        
        # Store in cache
        self.cache[cache_key] = {
            'data': result,
            'expires': time.time() + self.ttl_seconds
        }
        
        return result

# Validation middleware
async def validation_middleware(request: Dict[str, Any], next: RequestHandler) -> Any:
    """Validate request parameters"""
    method = request.get('method', '')
    params = request.get('params', {})
    
    # Validate resources/read requests
    if method == "resources/read":
        if not params.get('uri'):
            raise ValueError("Missing required parameter: uri")
        
        if not isinstance(params['uri'], str):
            raise TypeError("Parameter 'uri' must be a string")
    
    # Validate tools/call requests
    if method == "tools/call":
        if not params.get('name'):
            raise ValueError("Missing required parameter: name")
        
        if 'arguments' in params and not isinstance(params['arguments'], dict):
            raise TypeError("Parameter 'arguments' must be a dict")
    
    return await next(request)

# Usage example
def create_middleware_server():
    """Create server with middleware"""
    server = MiddlewareMCP(
        name="middleware-example",
        version="1.0.0"
    )
    
    # Apply middlewares
    all_methods = ["resources/list", "resources/read", "tools/list", "tools/call"]
    server.use(all_methods, logging_middleware)
    
    # Rate limiting
    rate_limiter = RateLimiter(window_seconds=60, max_requests=100)
    server.use(["resources/read", "tools/call"], rate_limiter.middleware)
    
    # Caching
    cache = CacheMiddleware(ttl_seconds=30)
    server.use(["resources/list", "resources/read"], cache.middleware)
    
    # Validation
    server.use(["resources/read", "tools/call"], validation_middleware)
    
    # Define handlers with middleware applied
    @server.list_resources()
    async def list_resources() -> List[Dict[str, Any]]:
        """List available resources"""
        # Middleware will be applied automatically
        return [
            {
                "uri": "example://resource",
                "name": "Example Resource",
                "mimeType": "text/plain",
            },
        ]
    
    @server.resource("example://*")
    async def read_resource(uri: str) -> str:
        """Read resource with middleware"""
        # All configured middleware will run before this handler
        return f"Resource content from {uri} with middleware"
    
    @server.tool(
        name="example_tool",
        description="Example tool with middleware",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
        }
    )
    async def example_tool(message: str) -> str:
        """Tool execution with middleware"""
        return f"Processed: {message}"
    
    return server

# Run server
if __name__ == "__main__":
    import sys
    
    server = create_middleware_server()
    print("Middleware MCP server running", file=sys.stderr)
    server.run()
```

## Troubleshooting Common Issues

### Connection Issues

1. **Server not starting**
   ```bash
   # Check if port is in use (for HTTP transport)
   lsof -i :3000
   
   # Check process permissions
   ls -la server.js
   chmod +x server.js
   ```

2. **Client can't connect**
   ```typescript
   // Add connection timeout
   const client = new Client({ name: "debug-client", version: "1.0.0" });
   
   try {
     await Promise.race([
       client.connect(transport),
       new Promise((_, reject) => 
         setTimeout(() => reject(new Error("Connection timeout")), 10000)
       )
     ]);
   } catch (error) {
     console.error("Connection failed:", error);
     // Check transport configuration
   }
   ```

### Protocol Issues

1. **Version mismatch**
   ```typescript
   // Handle version negotiation
   server.setRequestHandler("initialize", async (request) => {
     const clientVersion = request.params.protocolVersion;
     const serverVersion = "2025-06-18";
     
     if (!isVersionCompatible(clientVersion, serverVersion)) {
       throw new Error(
         `Protocol version mismatch. Client: ${clientVersion}, Server: ${serverVersion}`
       );
     }
     
     return {
       protocolVersion: serverVersion,
       capabilities: server.capabilities,
       serverInfo: server.info,
     };
   });
   ```

2. **Invalid JSON-RPC messages**
   ```python
   # Add message validation
   def validate_jsonrpc_message(message):
       if "jsonrpc" not in message or message["jsonrpc"] != "2.0":
           raise ValueError("Invalid JSON-RPC version")
       
       if "method" in message:  # Request or notification
           if not isinstance(message["method"], str):
               raise ValueError("Method must be a string")
       
       if "id" in message and message["id"] is None:
           raise ValueError("ID cannot be null")
   ```

### Performance Issues

1. **Slow resource reading**
   ```typescript
   // Implement streaming for large files
   server.setRequestHandler("resources/read", async (request) => {
     const { uri } = request.params;
     const filePath = uri.replace("file://", "");
     
     // Check file size
     const stats = await fs.stat(filePath);
     if (stats.size > 10 * 1024 * 1024) { // 10MB
       // Return reference instead of content
       return {
         contents: [{
           uri,
           mimeType: "application/x-large-file",
           text: JSON.stringify({
             size: stats.size,
             message: "File too large. Use streaming endpoint.",
             streamUri: `stream://${filePath}`
           })
         }]
       };
     }
     
     // Normal file reading for smaller files
     const content = await fs.readFile(filePath, "utf-8");
     return {
       contents: [{ uri, mimeType: "text/plain", text: content }]
     };
   });
   ```

2. **Memory leaks**
   ```python
   # Implement resource cleanup
   class MCPServer:
       def __init__(self):
           self.resources = []
           self.cleanup_interval = 300  # 5 minutes
           self._start_cleanup_task()
       
       def _start_cleanup_task(self):
           async def cleanup():
               while True:
                   await asyncio.sleep(self.cleanup_interval)
                   self._cleanup_expired_resources()
           
           asyncio.create_task(cleanup())
       
       def _cleanup_expired_resources(self):
           # Remove expired cached resources
           now = time.time()
           self.resources = [
               r for r in self.resources
               if not hasattr(r, 'expires') or r.expires > now
           ]
   ```

### Debugging Tips

1. **Enable verbose logging**
   ```python
   # Set environment variable
   import os
   os.environ["MCP_LOG_LEVEL"] = "debug"
   
   # Or configure logging in code
   import logging
   
   # Set up detailed logging
   logging.basicConfig(
       level=logging.DEBUG,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
   )
   
   # Get logger for your module
   logger = logging.getLogger(__name__)
   logger.setLevel(logging.DEBUG)
   ```

2. **Protocol tracing**
   ```python
   # Log all protocol messages
   class DebugTransport(StdioServerTransport):
       async def send(self, message):
           print(f">>> {json.dumps(message, indent=2)}")
           await super().send(message)
       
       async def receive(self):
           message = await super().receive()
           print(f"<<< {json.dumps(message, indent=2)}")
           return message
   ```

3. **Health checks**
   ```python
   # Add health endpoint
   import time
   import json
   import psutil
   from mcp.server.fastmcp import FastMCP
   
   mcp = FastMCP()
   SERVER_START_TIME = time.time()
   
   @mcp.tool(
       name="health",
       description="Get server health status"
   )
   async def health_check() -> str:
       """Return server health information"""
       process = psutil.Process()
       
       health_info = {
           "status": "healthy",
           "uptime": time.time() - SERVER_START_TIME,
           "memory": {
               "rss": process.memory_info().rss,
               "vms": process.memory_info().vms,
               "percent": process.memory_percent()
           },
           "cpu_percent": process.cpu_percent(interval=0.1),
           "version": mcp.version,
       }
       
       return json.dumps(health_info, indent=2)
   ```

## Next Steps

- **Resources**: Additional learning resources and references
- **Protocol Specification**: Deep dive into protocol details
- **Security**: Best practices for secure MCP implementations