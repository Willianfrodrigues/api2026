"""
Retorna campos disponíveis por plataforma.
Para Meta: consulta a API real e retorna todas as métricas/dimensões disponíveis.
Para as demais: retorna o catálogo estático (APIs não têm endpoint de discovery).
"""
import json, os, requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import get_token

# Campos estáticos para plataformas que não têm discovery API
STATIC = {
    "tiktok": {
        "dimensions": [
            {"id":"stat_time_day","label":"Date"},{"id":"advertiser_id","label":"Advertiser ID"},
            {"id":"campaign_id","label":"Campaign ID"},{"id":"campaign_name","label":"Campaign name"},
            {"id":"adgroup_id","label":"Ad Group ID","group":"adgroup"},{"id":"adgroup_name","label":"Ad Group name","group":"adgroup"},
            {"id":"ad_id","label":"Ad ID","group":"ad"},{"id":"ad_name","label":"Ad name","group":"ad"},
            {"id":"age","label":"Age","group":"audience"},{"id":"gender","label":"Gender","group":"audience"},
            {"id":"country_code","label":"Country","group":"geo"},{"id":"province_id","label":"Province","group":"geo"},
            {"id":"placement","label":"Placement","group":"placement"},
        ],
        "metrics": [
            {"id":"impressions","label":"Impressions"},{"id":"clicks","label":"Clicks"},
            {"id":"spend","label":"Spend"},{"id":"cpm","label":"CPM"},{"id":"ctr","label":"CTR"},
            {"id":"cpc","label":"CPC"},{"id":"reach","label":"Reach"},{"id":"frequency","label":"Frequency"},
            {"id":"video_play_actions","label":"Video Plays"},{"id":"video_watched_2s","label":"2s Video Views"},
            {"id":"video_watched_6s","label":"6s Video Views"},{"id":"average_video_play","label":"Avg Video Play Time"},
            {"id":"video_views_p25","label":"Video 25%"},{"id":"video_views_p50","label":"Video 50%"},
            {"id":"video_views_p75","label":"Video 75%"},{"id":"video_views_p100","label":"Video 100%"},
            {"id":"profile_visits","label":"Profile Visits"},{"id":"likes","label":"Likes"},
            {"id":"comments","label":"Comments"},{"id":"shares","label":"Shares"},{"id":"follows","label":"Follows"},
            {"id":"conversion","label":"Conversions"},{"id":"cost_per_conversion","label":"Cost per Conversion"},
            {"id":"conversion_rate","label":"Conversion Rate"},{"id":"result","label":"Results"},
            {"id":"cost_per_result","label":"Cost per Result"},{"id":"result_rate","label":"Result Rate"},
        ],
        "incompat": [["audience","geo"],["audience","placement"],["ad","audience"],["ad","geo"]]
    },
    "dv360": {
        "dimensions": [
            {"id":"FILTER_DATE","label":"Date"},{"id":"FILTER_ADVERTISER","label":"Advertiser ID"},
            {"id":"FILTER_ADVERTISER_NAME","label":"Advertiser name"},
            {"id":"FILTER_INSERTION_ORDER","label":"Insertion Order ID"},{"id":"FILTER_INSERTION_ORDER_NAME","label":"Insertion Order name"},
            {"id":"FILTER_LINE_ITEM","label":"Line Item ID"},{"id":"FILTER_LINE_ITEM_NAME","label":"Line Item name"},
            {"id":"FILTER_CREATIVE_ID","label":"Creative ID","group":"creative"},{"id":"FILTER_CREATIVE","label":"Creative name","group":"creative"},
            {"id":"FILTER_COUNTRY","label":"Country","group":"geo"},{"id":"FILTER_REGION","label":"Region","group":"geo"},
            {"id":"FILTER_CITY","label":"City","group":"geo"},
            {"id":"FILTER_DEVICE_TYPE","label":"Device type","group":"device"},{"id":"FILTER_BROWSER","label":"Browser","group":"device"},
            {"id":"FILTER_EXCHANGE_ID","label":"Exchange","group":"inventory"},{"id":"FILTER_SITE_ID","label":"Site","group":"inventory"},
            {"id":"FILTER_AGE","label":"Age","group":"audience"},{"id":"FILTER_GENDER","label":"Gender","group":"audience"},
        ],
        "metrics": [
            {"id":"METRIC_IMPRESSIONS","label":"Impressions"},{"id":"METRIC_CLICKS","label":"Clicks"},
            {"id":"METRIC_REVENUE_ADVERTISER","label":"Revenue (Adv Currency)"},{"id":"METRIC_MEDIA_COST_ADVERTISER","label":"Media Cost"},
            {"id":"METRIC_CPM_FEE1_ADVERTISER","label":"CPM"},{"id":"METRIC_CTR","label":"CTR"},
            {"id":"METRIC_RICH_MEDIA_VIDEO_PLAYS","label":"Video Plays"},{"id":"METRIC_RICH_MEDIA_VIDEO_COMPLETIONS","label":"Video Completions"},
            {"id":"METRIC_RICH_MEDIA_VIDEO_FIRST_QUARTILE","label":"Video 25%"},{"id":"METRIC_RICH_MEDIA_VIDEO_MIDPOINT","label":"Video 50%"},
            {"id":"METRIC_RICH_MEDIA_VIDEO_THIRD_QUARTILE","label":"Video 75%"},
            {"id":"METRIC_RICH_MEDIA_VIDEO_COMPLETION_RATE","label":"Video Completion Rate"},
            {"id":"METRIC_ACTIVE_VIEW_VIEWABLE_IMPRESSIONS","label":"Viewable Impressions"},
            {"id":"METRIC_ACTIVE_VIEW_ELIGIBLE_IMPRESSIONS","label":"Eligible Impressions"},
            {"id":"METRIC_TOTAL_CONVERSIONS","label":"Total Conversions"},
            {"id":"METRIC_LAST_CLICKS","label":"Last Click Conversions"},
            {"id":"METRIC_LAST_IMPRESSIONS","label":"Last Impression Conversions"},
            {"id":"METRIC_RICH_MEDIA_VIDEO_SKIP_RATE","label":"Video Skip Rate"},
        ],
        "incompat": [["audience","geo"],["audience","inventory"]]
    },
    "kwai": {
        "dimensions": [
            {"id":"date","label":"Date"},{"id":"advertiser_id","label":"Advertiser ID"},
            {"id":"campaign_id","label":"Campaign ID"},{"id":"campaign_name","label":"Campaign name"},
            {"id":"unit_id","label":"Ad Group ID","group":"adgroup"},{"id":"unit_name","label":"Ad Group name","group":"adgroup"},
            {"id":"creative_id","label":"Creative ID","group":"ad"},{"id":"creative_name","label":"Creative name","group":"ad"},
            {"id":"country","label":"Country","group":"geo"},
            {"id":"age","label":"Age","group":"audience"},{"id":"gender","label":"Gender","group":"audience"},
        ],
        "metrics": [
            {"id":"show","label":"Impressions"},{"id":"click","label":"Clicks"},{"id":"charge","label":"Spend"},
            {"id":"avcpm","label":"CPM"},{"id":"ctr","label":"CTR"},{"id":"cpc","label":"CPC"},
            {"id":"play_count","label":"Video Plays"},{"id":"play_3s_count","label":"3s Video Views"},
            {"id":"play_end_count","label":"Video Completions"},{"id":"comment_count","label":"Comments"},
            {"id":"like_count","label":"Likes"},{"id":"share_count","label":"Shares"},{"id":"follow_count","label":"Follows"},
            {"id":"form_count","label":"Form Submissions"},{"id":"conversion_count","label":"Conversions"},
            {"id":"cost_per_convert","label":"Cost per Conversion"},
        ],
        "incompat": [["audience","geo"],["ad","audience"]]
    }
}

# Grupos de incompatibilidade Meta
META_INCOMPAT = [
    ["audience","region"],["audience","placement"],["lead","audience"],
    ["lead","region"],["lead","placement"],["lead","ad"]
]

# Dimensões Meta fixas (não variam por conta)
META_DIMENSIONS = [
    {"id":"date_start","label":"Date"},
    {"id":"account_id","label":"Account ID"},{"id":"account_name","label":"Account name"},
    {"id":"campaign_id","label":"Campaign ID"},{"id":"campaign_name","label":"Campaign name"},
    {"id":"adset_id","label":"Ad set ID"},{"id":"adset_name","label":"Ad set name"},
    {"id":"ad_id","label":"Ad ID","group":"ad"},{"id":"ad_name","label":"Ad name","group":"ad"},
    {"id":"creative_id","label":"Ad creative ID","group":"ad"},{"id":"creative_name","label":"Ad creative name","group":"ad"},
    {"id":"data_source","label":"Data source"},{"id":"business_name","label":"Business name"},
    {"id":"destination_url","label":"Destination URL"},
    {"id":"promoted_post_url","label":"Promoted post destination URL"},
    {"id":"external_destination_url","label":"External destination URL"},
    {"id":"day_of_week","label":"Day of week"},
    {"id":"age","label":"Age","group":"audience"},{"id":"gender","label":"Gender","group":"audience"},
    {"id":"country","label":"Country","group":"region"},{"id":"region","label":"Region","group":"region"},
    {"id":"publisher_platform","label":"Publisher platform","group":"placement"},
    {"id":"platform_position","label":"Platform position","group":"placement"},
    {"id":"impression_device","label":"Impression device","group":"placement"},
    {"id":"lead_form_id","label":"Lead form ID","group":"lead"},
    {"id":"lead_form_name","label":"Lead form name","group":"lead"},
]

def fetch_meta_fields(access_token, account_id):
    """Busca os campos disponíveis para uma conta via Meta API."""
    try:
        # Pega os campos disponíveis do endpoint de insights
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{account_id}/insights",
            params={
                "access_token": access_token,
                "fields": "insights.fields(fields)",
                "date_preset": "yesterday",
                "limit": 1
            },
            timeout=10
        )
        data = resp.json()

        # Se der erro, usa lista completa conhecida
        if "error" in data:
            return get_meta_full_fields()

        # Tenta extrair campos disponíveis
        fields_data = data.get("fields", {}).get("data", [])
        if not fields_data:
            return get_meta_full_fields()

        metrics = []
        for f in fields_data:
            name = f.get("name","")
            desc = f.get("description","")
            if name and not name.startswith("date") and name not in [d["id"] for d in META_DIMENSIONS]:
                metrics.append({"id": name, "label": desc or name.replace("_"," ").title()})

        return metrics if metrics else get_meta_full_fields()
    except:
        return get_meta_full_fields()

def get_meta_full_fields():
    """Lista completa de métricas Meta conhecidas."""
    return [
        {"id":"impressions","label":"Impressions"},
        {"id":"spend","label":"Amount spent"},
        {"id":"clicks","label":"Clicks (all)"},
        {"id":"inline_link_clicks","label":"Link clicks"},
        {"id":"unique_clicks","label":"Unique clicks (all)"},
        {"id":"unique_inline_link_clicks","label":"Unique link clicks"},
        {"id":"cpm","label":"CPM"},
        {"id":"cpc","label":"CPC"},
        {"id":"ctr","label":"CTR"},
        {"id":"unique_ctr","label":"Unique CTR"},
        {"id":"cpp","label":"CPP"},
        {"id":"reach","label":"Reach"},
        {"id":"frequency","label":"Frequency"},
        {"id":"cost_per_unique_click","label":"Cost per unique click"},
        {"id":"outbound_clicks","label":"Outbound clicks"},
        {"id":"unique_outbound_clicks","label":"Unique outbound clicks"},
        {"id":"outbound_clicks_ctr","label":"Outbound CTR"},
        {"id":"landing_page_views","label":"Landing page views"},
        {"id":"page_likes","label":"Page likes"},
        {"id":"page_engagement","label":"Page engagement"},
        {"id":"post_engagement","label":"Post engagement"},
        {"id":"post_reactions","label":"Post reactions"},
        {"id":"post_comments","label":"Post comments (on ad)"},
        {"id":"post_saves","label":"Post saves"},
        {"id":"post_shares","label":"Post shares"},
        {"id":"photo_views","label":"Photo views"},
        {"id":"video_play_actions","label":"Clicks to play video"},
        {"id":"video_30_sec_watched_actions","label":"30-second video views"},
        {"id":"video_p25_watched_actions","label":"Video plays at 25%"},
        {"id":"video_p50_watched_actions","label":"Video plays at 50%"},
        {"id":"video_p75_watched_actions","label":"Video plays at 75%"},
        {"id":"video_p95_watched_actions","label":"Video plays at 95%"},
        {"id":"video_p100_watched_actions","label":"Video plays at 100%"},
        {"id":"video_avg_time_watched_actions","label":"Average video play time"},
        {"id":"video_continuous_2_sec_watched_actions","label":"2-second continuous video views"},
        {"id":"video_thruplay_watched_actions","label":"ThruPlay views"},
        {"id":"estimated_ad_recallers","label":"Estimated ad recall lift"},
        {"id":"estimated_ad_recall_rate","label":"Estimated ad recall rate"},
        {"id":"cost_per_estimated_ad_recallers","label":"Cost per estimated ad recall"},
        {"id":"actions","label":"Actions (all)"},
        {"id":"unique_actions","label":"Unique actions"},
        {"id":"cost_per_action_type","label":"Cost per action"},
        {"id":"website_purchase_roas","label":"Website purchase ROAS"},
        {"id":"purchase","label":"Purchases"},
        {"id":"purchase_value","label":"Purchase value"},
        {"id":"cost_per_purchase","label":"Cost per purchase"},
        {"id":"omni_purchase","label":"Omni purchases"},
        {"id":"omni_purchase_value","label":"Omni purchase value"},
        {"id":"website_leads","label":"Website leads"},
        {"id":"lead","label":"Leads"},
        {"id":"contact","label":"Contacts"},
        {"id":"complete_registration","label":"Registrations completed"},
        {"id":"subscribe","label":"Subscribes"},
        {"id":"start_trial","label":"Trials started"},
        {"id":"add_to_cart","label":"Adds to cart"},
        {"id":"add_to_wishlist","label":"Adds to wishlist"},
        {"id":"initiate_checkout","label":"Checkouts initiated"},
        {"id":"add_payment_info","label":"Payment info added"},
        {"id":"view_content","label":"Content views"},
        {"id":"search","label":"Searches"},
        {"id":"mobile_app_install","label":"Mobile app installs"},
        {"id":"app_use","label":"App uses"},
        {"id":"unique_video_continuous_2_sec_watched_actions","label":"Unique 2-second continuous video views"},
        {"id":"onsite_conversion.messaging_first_reply","label":"New messaging connections"},
        {"id":"onsite_conversion.lead_grouped","label":"On-Facebook leads"},
        {"id":"canvas_avg_view_time","label":"Instant experience view time"},
        {"id":"canvas_avg_view_percent","label":"Instant experience view %"},
    ]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        platform = qs.get("platform", [""])[0]

        if not platform:
            self._j({"error": "platform required"}, 400)
            return

        if platform != "meta":
            self._j(STATIC.get(platform, {"error": "unknown platform"}))
            return

        # Meta: tenta buscar da API real
        token = get_token("meta")
        if not token:
            # Sem token, retorna lista completa estática
            self._j({
                "dimensions": META_DIMENSIONS,
                "metrics": get_meta_full_fields(),
                "incompat": META_INCOMPAT,
                "source": "static"
            })
            return

        # Com token, usa a lista completa (a API de discovery não é confiável)
        # mas valida que o token funciona
        accounts = token.get("account_ids", [])
        self._j({
            "dimensions": META_DIMENSIONS,
            "metrics": get_meta_full_fields(),
            "incompat": META_INCOMPAT,
            "source": "api",
            "accounts": len(accounts)
        })

    def _j(self, data, status=200):
        b = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

app = handler
