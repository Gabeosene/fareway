import urllib.request
import urllib.parse
import json
import time
# Try to import rich, fallback if not present (though it should be)
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:
    class Console:
        def print(self, msg, **kwargs): print(msg)
        def rule(self, msg): print(f"--- {msg} ---")
        def status(self, msg, **kwargs): 
            print(msg)
            return self
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Panel:
        def __init__(self, msg, **kwargs): self.msg = msg
        def __str__(self): return str(self.msg)
    console = Console()

BASE_URL = "http://localhost:8000"

def post_json(endpoint, data):
    url = f"{BASE_URL}{endpoint}"
    json_data = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=json_data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                return json.loads(response.read().decode())
    except Exception as e:
        console.print(f"[red]Error contacting {url}: {e}[/red]")
        return None

def post_empty(endpoint, params=None):
    url = f"{BASE_URL}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status == 200
    except Exception as e:
        console.print(f"[red]Error contacting {url}: {e}[/red]")
        return False

def run_scenario():
    console.print(Panel("[bold cyan]Silent Photon: Automated Scenario Runner[/bold cyan]", expand=False))

    # 1. Baseline
    console.rule("[bold]Step 1: Baseline Check (Reggel)[/bold]")
    # u_std = János (Standard)
    # link_szechenyi = Chain Bridge
    q_std = post_json("/api/quote", {"user_id": "u_std", "link_id": "link_szechenyi"})
    
    if not q_std:
        console.print("[red]Failed to get initial quote. Is the server running on port 8000?[/red]")
        return
    
    price = q_std.get('final_price')
    console.print(f"Baseline Quote (Standard User): [green]{price} HUF[/green]")

    # 2. Trigger Accident
    console.rule("[bold]Step 2: Triggering Accident (Dugó)[/bold]")
    if post_empty("/simulate/accident", {"link_id": "link_szechenyi"}):
        console.print("[bold red]>> ACCIDENT TRIGGERED ON CHAIN BRIDGE <<[/bold red]")
    else:
        console.print("[red]Failed to trigger accident[/red]")
        return
    
    # Wait for simulation to react
    console.print("[yellow]Waiting 3 seconds for congestion to build...[/yellow]")
    time.sleep(3)

    # 3. Check Surge Pricing
    console.rule("[bold]Step 3: Surge Pricing Analysis[/bold]")
    
    # Standard User again
    q_surge = post_json("/api/quote", {"user_id": "u_std", "link_id": "link_szechenyi"})
    if q_surge:
        s_price = q_surge.get('final_price')
        mult = q_surge.get('price_multiplier')
        mult_text = f" (Multiplier: x{mult:.1f})" if isinstance(mult, (int, float)) else ""
        console.print(f"Surge Quote (Standard User): [bold red]{s_price} HUF[/bold red]{mult_text}")
    
    # Equity User (Eva)
    q_equity = post_json("/api/quote", {"user_id": "u_eq", "link_id": "link_szechenyi"})
    if q_equity:
        e_price = q_equity.get('final_price')
        disc = q_equity.get('discount_amount', 0)
        console.print(f"Surge Quote (Equity User):   [bold green]{e_price} HUF[/bold green] (Discount: -{disc} HUF)")

    # 4. Behavioral Shift
    console.rule("[bold]Step 4: Behavioral Shift (Metro)[/bold]")
    # Flexible User (Zoltán) -> Metro 4
    q_metro = post_json("/api/quote", {"user_id": "u_flex", "link_id": "link_m4"})
    if q_metro and q_surge:
        m_price = q_metro.get('final_price')
        s_price = q_surge.get('final_price')
        console.print(f"Metro Quote (Flexible User): [cyan]{m_price} HUF[/cyan]")
        
        diff = s_price - m_price
        if diff > 0:
            console.print(f"[bold]>> User chooses Metro (Saves {diff} HUF)[/bold]")

    console.print(Panel("[bold green]Scenario Completed[/bold green]", expand=False))

if __name__ == "__main__":
    run_scenario()
