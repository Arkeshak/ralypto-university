"""Product Catalog: realistic brand names, high-res photography, and offline vector illustrations."""
from __future__ import annotations

import html
import urllib.parse

# Curated catalog of realistic, recognizable retail products across business profiles
CATALOG = {
    # ------------------------------------------------------------- Supermarket Profile
    "supermarket": {
        "Dairy": [
            {
                "name": "Anchor Full Cream Milk Powder (400g)",
                "unit": "400g pack",
                "image": "https://images.unsplash.com/photo-1550583724-b2692b85b150?auto=format&fit=crop&w=300&q=80",
                "icon": "dairy",
            },
            {
                "name": "Highland Pure Fresh Milk (1L)",
                "unit": "1L carton",
                "image": "https://images.unsplash.com/photo-1563636619-e9143da7973b?auto=format&fit=crop&w=300&q=80",
                "icon": "dairy",
            },
            {
                "name": "Kotmale Natural Cheddar Cheese (200g)",
                "unit": "200g block",
                "image": "https://images.unsplash.com/photo-1486297678162-eb2a19b0a32d?auto=format&fit=crop&w=300&q=80",
                "icon": "cheese",
            },
            {
                "name": "Pelwatte Salted Butter (200g)",
                "unit": "200g foil",
                "image": "https://images.unsplash.com/photo-1589985270826-4b7bb135bc9d?auto=format&fit=crop&w=300&q=80",
                "icon": "dairy",
            },
            {
                "name": "Elephant House Vanilla Ice Cream (1L)",
                "unit": "1L tub",
                "image": "https://images.unsplash.com/photo-1570197788417-0e82375c9371?auto=format&fit=crop&w=300&q=80",
                "icon": "dessert",
            },
            {
                "name": "Happy Cow Cheese Triangles (140g)",
                "unit": "8 portions",
                "image": "https://images.unsplash.com/photo-1528735602780-2552fd46c7af?auto=format&fit=crop&w=300&q=80",
                "icon": "cheese",
            },
        ],
        "Beverages": [
            {
                "name": "Coca-Cola Original Taste (1.5L)",
                "unit": "1.5L PET bottle",
                "image": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?auto=format&fit=crop&w=300&q=80",
                "icon": "drink",
            },
            {
                "name": "Elephant House Cream Soda (1.5L)",
                "unit": "1.5L bottle",
                "image": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?auto=format&fit=crop&w=300&q=80",
                "icon": "drink",
            },
            {
                "name": "Nescafe Classic Instant Coffee (100g)",
                "unit": "100g glass jar",
                "image": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?auto=format&fit=crop&w=300&q=80",
                "icon": "coffee",
            },
            {
                "name": "Dilmah Premium Pure Ceylon Tea (100 Bags)",
                "unit": "100 tea bags",
                "image": "https://images.unsplash.com/photo-1576092768241-dec231879fc3?auto=format&fit=crop&w=300&q=80",
                "icon": "tea",
            },
            {
                "name": "Milo Malt Chocolate Beverage (400g)",
                "unit": "400g pouch",
                "image": "https://images.unsplash.com/photo-1544787219-7f47ccb76574?auto=format&fit=crop&w=300&q=80",
                "icon": "drink",
            },
            {
                "name": "Red Bull Energy Drink (250ml)",
                "unit": "250ml can",
                "image": "https://images.unsplash.com/photo-1551024709-8f23befc6f87?auto=format&fit=crop&w=300&q=80",
                "icon": "drink",
            },
            {
                "name": "Sprite Lemon-Lime Sparkling (1.5L)",
                "unit": "1.5L bottle",
                "image": "https://images.unsplash.com/photo-1625772299848-391b6a87d7b3?auto=format&fit=crop&w=300&q=80",
                "icon": "drink",
            },
            {
                "name": "Sunquick Orange Fruit Cordial (840ml)",
                "unit": "840ml bottle",
                "image": "https://images.unsplash.com/photo-1613478223719-2ab802602423?auto=format&fit=crop&w=300&q=80",
                "icon": "drink",
            },
        ],
        "Produce": [
            {
                "name": "Fresh Red Onions (1kg)",
                "unit": "1kg net pack",
                "image": "https://images.unsplash.com/photo-1618512496248-a07fe83aa8cb?auto=format&fit=crop&w=300&q=80",
                "icon": "produce",
            },
            {
                "name": "Crisp Bell Peppers Mix (500g)",
                "unit": "500g punnet",
                "image": "https://images.unsplash.com/photo-1563565375-f3fdfdbefa83?auto=format&fit=crop&w=300&q=80",
                "icon": "produce",
            },
            {
                "name": "Organic Cavendish Bananas (1kg)",
                "unit": "1kg cluster",
                "image": "https://images.unsplash.com/photo-1571771894821-ce9b6c11b08e?auto=format&fit=crop&w=300&q=80",
                "icon": "fruit",
            },
            {
                "name": "Fresh Nuwara Eliya Carrots (1kg)",
                "unit": "1kg pack",
                "image": "https://images.unsplash.com/photo-1598170845058-32b9d6a5da37?auto=format&fit=crop&w=300&q=80",
                "icon": "produce",
            },
            {
                "name": "Crisp Royal Gala Apples (1kg)",
                "unit": "1kg bag",
                "image": "https://images.unsplash.com/photo-1560806887-1e4cd0b6cbd6?auto=format&fit=crop&w=300&q=80",
                "icon": "fruit",
            },
            {
                "name": "Seedless Sweet Green Grapes (500g)",
                "unit": "500g box",
                "image": "https://images.unsplash.com/photo-1596363505729-4190a9506133?auto=format&fit=crop&w=300&q=80",
                "icon": "fruit",
            },
        ],
        "Dry goods": [
            {
                "name": "Prima KottuMee Hot & Spicy Noodles",
                "unit": "80g pack",
                "image": "https://images.unsplash.com/photo-1612927601601-6638404737ce?auto=format&fit=crop&w=300&q=80",
                "icon": "noodles",
            },
            {
                "name": "Munchee Super Cream Crackers (500g)",
                "unit": "500g family pack",
                "image": "https://images.unsplash.com/photo-1590080875515-8a3a8dc5735e?auto=format&fit=crop&w=300&q=80",
                "icon": "biscuit",
            },
            {
                "name": "Maliban Gold Marie Biscuits (300g)",
                "unit": "300g pack",
                "image": "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?auto=format&fit=crop&w=300&q=80",
                "icon": "biscuit",
            },
            {
                "name": "Maggi 2-Minute Chicken Noodles (4-Pack)",
                "unit": "4 x 73g bundle",
                "image": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=300&q=80",
                "icon": "noodles",
            },
            {
                "name": "Keells Premium White Basmati Rice (5kg)",
                "unit": "5kg woven sack",
                "image": "https://images.unsplash.com/photo-1586201375761-83865001e31c?auto=format&fit=crop&w=300&q=80",
                "icon": "grain",
            },
            {
                "name": "Fortune Pure Sunflower Oil (1L)",
                "unit": "1L bottle",
                "image": "https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?auto=format&fit=crop&w=300&q=80",
                "icon": "oil",
            },
            {
                "name": "Kist Real Strawberry Jam (500g)",
                "unit": "500g jar",
                "image": "https://images.unsplash.com/photo-1577069808021-50e50e18ef77?auto=format&fit=crop&w=300&q=80",
                "icon": "jam",
            },
            {
                "name": "MD Authentic Tomato Ketchup (400g)",
                "unit": "400g glass bottle",
                "image": "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?auto=format&fit=crop&w=300&q=80",
                "icon": "sauce",
            },
        ],
    },

    # ------------------------------------------------------------- Pharmacy Profile
    "pharmacy": {
        "Medicine": [
            {
                "name": "Paracetamol Tablets (500mg, 100s)",
                "unit": "Box of 100",
                "image": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Panadol Extra Pain Relief (48 Tablets)",
                "unit": "Box of 48",
                "image": "https://images.unsplash.com/photo-1550572017-edd951aa8f72?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Amoxicillin Antibiotic (500mg, 20s)",
                "unit": "Blister pack of 20",
                "image": "https://images.unsplash.com/photo-1471864190281-a93a3070b6de?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Cetirizine 24h Allergy Relief (10mg, 30s)",
                "unit": "Box of 30",
                "image": "https://images.unsplash.com/photo-1587854692152-cbe660dbde88?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Omeprazole Acid Reducer (20mg, 28s)",
                "unit": "Box of 28",
                "image": "https://images.unsplash.com/photo-1576602976047-174e57a47881?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Ibuprofen Rapid Action (400mg, 30s)",
                "unit": "Box of 30",
                "image": "https://images.unsplash.com/photo-1584017911766-d451b3d0e843?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
        ],
        "Supplements": [
            {
                "name": "Vitamin C Chewable (500mg, 60s)",
                "unit": "Bottle of 60",
                "image": "https://images.unsplash.com/photo-1550572017-edd951aa8f72?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Pure Omega-3 Fish Oil (1000mg, 90s)",
                "unit": "Bottle of 90 softgels",
                "image": "https://images.unsplash.com/photo-1577401239170-897942555fb3?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Vitamin D3 High Potency (1000IU, 60s)",
                "unit": "Bottle of 60",
                "image": "https://images.unsplash.com/photo-1512069772995-ec65ed45afd6?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
            {
                "name": "Complete Daily Multivitamins (90s)",
                "unit": "Bottle of 90",
                "image": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?auto=format&fit=crop&w=300&q=80",
                "icon": "pill",
            },
        ],
        "Hygiene": [
            {
                "name": "Dettol Antiseptic Disinfectant (500ml)",
                "unit": "500ml bottle",
                "image": "https://images.unsplash.com/photo-1584744982491-665216d95f8b?auto=format&fit=crop&w=300&q=80",
                "icon": "hygiene",
            },
            {
                "name": "Band-Aid Sterile Adhesive Strips (100s)",
                "unit": "Box of 100",
                "image": "https://images.unsplash.com/photo-1603398938378-e54eab446dde?auto=format&fit=crop&w=300&q=80",
                "icon": "hygiene",
            },
            {
                "name": "Lifebuoy Antibacterial Hand Wash (250ml)",
                "unit": "250ml pump bottle",
                "image": "https://images.unsplash.com/photo-1585421514284-efb74c2b69ba?auto=format&fit=crop&w=300&q=80",
                "icon": "hygiene",
            },
        ],
    },

    # ------------------------------------------------------------- Hardware Profile
    "hardware": {
        "Tools": [
            {
                "name": "Stanley Heavy Duty Claw Hammer (16oz)",
                "unit": "1 unit",
                "image": "https://images.unsplash.com/photo-1586864387967-d02ef85d93e8?auto=format&fit=crop&w=300&q=80",
                "icon": "tool",
            },
            {
                "name": "Bosch Professional Cordless Drill (12V)",
                "unit": "Kit with battery",
                "image": "https://images.unsplash.com/photo-1504148455328-c376907d081c?auto=format&fit=crop&w=300&q=80",
                "icon": "tool",
            },
            {
                "name": "Craftsman 6-Piece Heavy Screwdriver Set",
                "unit": "Set of 6",
                "image": "https://images.unsplash.com/photo-1581783342308-f792dbdd27c5?auto=format&fit=crop&w=300&q=80",
                "icon": "tool",
            },
        ],
        "Fasteners": [
            {
                "name": "Zinc-Plated Steel Wood Screws (Box 200)",
                "unit": "Box of 200",
                "image": "https://images.unsplash.com/photo-1608613304899-ea8098577e38?auto=format&fit=crop&w=300&q=80",
                "icon": "bolt",
            },
            {
                "name": "Heavy Duty Concrete Anchors M10 (50s)",
                "unit": "Pack of 50",
                "image": "https://images.unsplash.com/photo-1585338107529-13afc5f02586?auto=format&fit=crop&w=300&q=80",
                "icon": "bolt",
            },
        ],
        "Paint": [
            {
                "name": "Dulux Weathershield Exterior Paint (5L)",
                "unit": "5L can",
                "image": "https://images.unsplash.com/photo-1562259949-e8e7689d7828?auto=format&fit=crop&w=300&q=80",
                "icon": "paint",
            },
            {
                "name": "Gorilla Waterproof Clear Silicone (300ml)",
                "unit": "300ml cartridge",
                "image": "https://images.unsplash.com/photo-1589939705384-5185137a7f0f?auto=format&fit=crop&w=300&q=80",
                "icon": "paint",
            },
        ],
    },
}

# Offline high-contrast clean SVG illustrations as embedded data URIs
SVG_ICONS = {
    "dairy": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="12" y="16" width="24" height="26" rx="4" fill="#F0FDFA"/>'
        '<path d="M16 16V10a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v6"/>'
        '<path d="M24 24v8M20 28h8"/>'
        '</svg>'
    ),
    "drink": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M18 10h12v4H18z" fill="#CCFBF1"/>'
        '<path d="M16 14h16l2 28H14l2-28z" fill="#F0FDFA"/>'
        '<path d="M20 22h8M19 30h10"/>'
        '</svg>'
    ),
    "produce": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="24" cy="26" r="14" fill="#F0FDFA"/>'
        '<path d="M24 12c0-4 4-6 6-6s2 4-2 6"/>'
        '<path d="M18 26c3 4 9 4 12 0"/>'
        '</svg>'
    ),
    "pill": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="14" y="10" width="20" height="28" rx="10" transform="rotate(45 24 24)" fill="#F0FDFA"/>'
        '<line x1="14" y1="24" x2="34" y2="24" transform="rotate(45 24 24)"/>'
        '</svg>'
    ),
    "tool": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M14 34l18-18M28 12l8 8-4 4-8-8 4-4z" fill="#F0FDFA"/>'
        '<path d="M12 36l-4 4 4 4 4-4-4-4z"/>'
        '</svg>'
    ),
    "default": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" fill="none" stroke="#0F766E" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="8" y="12" width="32" height="28" rx="4" fill="#F0FDFA"/>'
        '<path d="M16 12V8a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v4"/>'
        '<line x1="8" y1="22" x2="40" y2="22"/>'
        '</svg>'
    ),
}


def _svg_data_uri(svg_str: str) -> str:
    return f"data:image/svg+xml;utf8,{urllib.parse.quote(svg_str)}"


def get_product_visuals(sku: str, name: str | None = None, category: str | None = None, profile: str = "supermarket") -> dict:
    """Resolve full commercial name, photo URL, and vector fallback for any SKU."""
    cat_items = CATALOG.get(profile, CATALOG["supermarket"])

    # If name is already branded, match by partial name or category
    clean_cat = category or "Dry goods"
    pool = cat_items.get(clean_cat) or next(iter(cat_items.values()))

    # Deterministic index from SKU number
    idx = 0
    if sku and "-" in sku:
        try:
            idx = int(sku.split("-")[1])
        except ValueError:
            idx = sum(ord(c) for c in sku)

    item_def = pool[idx % len(pool)]
    display_name = name if name and not name.endswith(f"item {idx}") and "item " not in name else item_def["name"]
    icon_type = item_def.get("icon", "default")
    svg = SVG_ICONS.get(icon_type, SVG_ICONS["default"])

    return {
        "sku": sku,
        "name": display_name,
        "category": clean_cat,
        "unit": item_def.get("unit", "Units"),
        "image": item_def["image"],
        "fallback_svg": _svg_data_uri(svg),
    }


def product_avatar_html(sku: str, name: str | None = None, category: str | None = None,
                        size: int = 48, radius: int = 8) -> str:
    """Returns an HTML img tag with real photo and zero-latency SVG fallback."""
    v = get_product_visuals(sku, name, category)
    esc_name = html.escape(v["name"])
    return (
        f'<img src="{v["image"]}" '
        f'onerror="this.onerror=null; this.src=\'{v["fallback_svg"]}\';" '
        f'alt="{esc_name}" loading="lazy" '
        f'style="width:{size}px; height:{size}px; min-width:{size}px; min-height:{size}px; '
        f'border-radius:{radius}px; object-fit:cover; border:1px solid #E2E8F0; '
        f'background:#F8FAFC; display:inline-block; vertical-align:middle; margin-right:10px;" />'
    )


def product_cell_html(sku: str, name: str | None = None, category: str | None = None,
                      subtext: str | None = None, size: int = 42) -> str:
    """Returns a rich product cell suitable for tables and card headers."""
    v = get_product_visuals(sku, name, category)
    esc_name = html.escape(v["name"])
    esc_sku = html.escape(sku)
    sub = f'<div style="font-size:0.75rem; color:#64748B;">{html.escape(subtext)}</div>' if subtext else (
        f'<div style="font-size:0.75rem; color:#64748B;">Product code: <code>{esc_sku}</code> • {html.escape(v["category"])}</div>'
    )
    img_tag = product_avatar_html(sku, name, category, size=size)
    return (
        f'<div style="display:flex; align-items:center; gap:10px;">'
        f'{img_tag}'
        f'<div style="line-height:1.25;">'
        f'<div style="font-weight:700; color:#0F172A; font-size:0.92rem;">{esc_name}</div>'
        f'{sub}'
        f'</div></div>'
    )
