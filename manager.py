import json
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

# --- Data Models ---

@dataclass
class NetworkLink:
    id: str
    name: str
    capacity: int
    base_price: int
    current_flow: int = 0
    current_ci: float = 0.0
    forecast_ci: float = 0.0
    current_price: int = 0
    price_multiplier: float = 1.0
    type: str = "road"
    coordinates: List[List[float]] = field(default_factory=list)

@dataclass
class UserProfile:
    id: str
    name: str
    tier: str  # 'standard', 'equity'
    balance: int
    
@dataclass
class Quote:
    id: str
    user_id: str
    route_id: str
    base_price: int
    final_price: int
    discount_amount: int
    discount_reason: str
    rewards_credits: int
    expires_at: float

@dataclass
class Reservation:
    id: str
    quote_id: str
    user_id: str
    status: str # 'HOLD', 'CONFIRMED', 'EXPIRED'
    expires_at: float
    confirmed_at: Optional[float] = None

# --- Core Logic ---

class CongestionTwin:
    """The 'Brain'. Manages state, pricing loop, and forecast."""
    def __init__(self, config: Dict):
        self.config = config
        self.links: Dict[str, NetworkLink] = {}
        self.users: Dict[str, UserProfile] = {}
        self.policy = config['policy']
        self._load_config()
        self.history: List[Dict] = [] # Telemetry log

    def _load_config(self):
        # Load Links
        for l in self.config['network']['links']:
            self.links[l['id']] = NetworkLink(
                id=l['id'],
                name=l['name'],
                capacity=l['capacity'],
                base_price=l['base_price_huf'],
                current_price=l['base_price_huf'],
                type=l.get('type', 'road'),
                coordinates=l.get('coordinates', [])
            )
        # Load Users
        for u in self.config['users']:
            self.users[u['id']] = UserProfile(
                id=u['id'],
                name=u['name'],
                tier=u['tier'],
                balance=u['balance_huf']
            )

    def tick(self):
        """Runs one simulation cycle (updates forecasts and prices)."""
        # 1. Update Forecasts (Simple persistence model for demo)
        #    Forecast = Current CI (smoothed)
        #    Price = Base * Multiplier
        
        target_ci = self.policy['congestion_target_ci']
        sensitivity = self.policy['price_sensitivity_factor']
        
        for link in self.links.values():
            # Calc CI
            raw_ci = link.current_flow / link.capacity if link.capacity > 0 else 0
            # Smooth it (alpha=0.1 for TUI smoothness at 10Hz)
            # 0.1 means it takes about 2 seconds to fully reflect a step change, which looks nice.
            alpha = 0.1
            prev_ci = link.current_ci
            link.current_ci = (alpha * raw_ci) + ((1 - alpha) * link.current_ci)
            
            # Forecast (Short horizon)
            # Add a trend component? (Derivative)
            trend = link.current_ci - prev_ci
            link.forecast_ci = link.current_ci + (trend * 5.0) # Extrapolate slightly
            
            # Pricing Rule
            # If Forecast > Target, Price increases linearly
            excess_congestion = max(0, link.forecast_ci - target_ci)
            
            # Surge Factor: Additional multiplier if congestion is rising fast
            surge_premium = 0.0
            if trend > 0.01: # Rapid rise
                surge_premium = 0.5 # Jump 50% immediately if accidents happen
                
            # Multiplier = 1 + (Excess * Sensitivity) + Surge
            multiplier = 1.0 + (excess_congestion * sensitivity) + surge_premium
            multiplier = max(1.0, multiplier)
            
            link.price_multiplier = multiplier
            link.current_price = int(link.base_price * multiplier)
            
    def ingest_observation(self, link_id: str, flow: int):
        if link_id in self.links:
            self.links[link_id].current_flow = flow

    def record_telemetry(self, event_type: str, details: Dict):
        self.history.append({
            "timestamp": time.time(),
            "type": event_type,
            "details": details
        })

class PolicyEngine:
    """The 'Heart'. Applies rules to prices."""
    def __init__(self, twin: CongestionTwin):
        self.twin = twin
        self.p_config = twin.policy

    def calculate_quote(self, user: UserProfile, link_id: str) -> Quote:
        link = self.twin.links[link_id]
        base_price = link.current_price
        
        # 1. Equity Discount
        discount = 0
        reason = ""
        final_price = base_price
        
        if user.tier == 'equity':
            # 50% discount
            disc_percent = self.p_config.get('equity_discount_percent', 0) / 100.0
            discount = int(base_price * disc_percent)
            final_price -= discount
            reason = "Equity Tier"
            
            # Cap: Equity users shouldn't pay more than original base if possible, 
            # but usually a flat % is safer for demo. 
            # Let's add a "Anti-Surge Protection":
            # If surge > 1.5x, cap equity price at 1.2x base?
            # For simplicity: Plain % discount is enough for 1-day demo.
        
        # 2. Rewards
        # Earn credits if link is empty (< 0.4 CI)
        rewards = 0
        if link.current_ci < self.p_config.get('reward_threshold_ci', 0.4):
            rewards = self.p_config.get('reward_amount_credits', 0)
            
        quote = Quote(
            id=f"q_{uuid.uuid4().hex[:6]}",
            user_id=user.id,
            route_id=link_id,
            base_price=base_price,
            final_price=final_price,
            discount_amount=discount,
            discount_reason=reason,
            rewards_credits=rewards,
            expires_at=time.time() + self.twin.config['simulation']['quote_expiry_sec']
        )
        return quote

class QuoteService:
    """The 'Cashier'. Manage Transaction State."""
    def __init__(self, twin: CongestionTwin, policy: PolicyEngine):
        self.twin = twin
        self.policy = policy
        self.active_quotes: Dict[str, Quote] = {}
        self.reservations: Dict[str, Reservation] = {}

    def create_quote(self, user_id: str, link_id: str) -> Quote:
        user = self.twin.users.get(user_id)
        if not user:
            raise ValueError("User not found")
        
        quote = self.policy.calculate_quote(user, link_id)
        self.active_quotes[quote.id] = quote
        return quote

    def reserve(self, quote_id: str) -> Reservation:
        quote = self.active_quotes.get(quote_id)
        if not quote:
            raise ValueError("Quote not found")
        if time.time() > quote.expires_at:
            raise ValueError("Quote expired")
            
        res = Reservation(
            id=f"r_{uuid.uuid4().hex[:6]}",
            quote_id=quote_id,
            user_id=quote.user_id,
            status="HOLD",
            expires_at=time.time() + self.twin.config['simulation']['reservation_expiry_sec']
        )
        self.reservations[res.id] = res
        return res

    def confirm(self, reservation_id: str) -> Dict:
        res = self.reservations.get(reservation_id)
        if not res:
            raise ValueError("Reservation not found")
        if res.status != "HOLD":
             # Idempotency check
            if res.status == "CONFIRMED":
                return {"status": "CONFIRMED", "note": "Already Confirmed"}
            raise ValueError("Reservation not valid for confirmation")
        if time.time() > res.expires_at:
            res.status = "EXPIRED"
            raise ValueError("Reservation expired")
            
        # Execute Transaction
        quote = self.active_quotes[res.quote_id]
        user = self.twin.users[res.user_id]
        
        if user.balance < quote.final_price:
            raise ValueError("Insufficient Funds")
            
        user.balance -= quote.final_price
        user.balance += quote.rewards_credits
        
        res.status = "CONFIRMED"
        res.confirmed_at = time.time()
        
        # Telemetry
        self.twin.record_telemetry("booking_confirmed", {
            "link": quote.route_id,
            "price": quote.final_price,
            "user_tier": user.tier,
            "ci_at_booking": self.twin.links[quote.route_id].current_ci
        })
        
        return {
            "status": "CONFIRMED",
            "receipt_amount": quote.final_price,
            "new_balance": user.balance,
            "rewards_earned": quote.rewards_credits
        }

# Factory to boostrap
_singleton_manager = None

def get_manager(config_path: str = "demo_config.json"):
    global _singleton_manager
    if _singleton_manager is None:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        twin = CongestionTwin(config)
        policy = PolicyEngine(twin)
        service = QuoteService(twin, policy)
        
        # Attach references for easy access
        # Python dynamic nature abuse for demo convenience? 
        # Better to return a container class.
        class Manager:
            pass
        mgr = Manager()
        mgr.twin = twin
        mgr.policy = policy
        mgr.service = service
        _singleton_manager = mgr
        
    return _singleton_manager
