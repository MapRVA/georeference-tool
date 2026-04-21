class CloudflareTunnelMiddleware:
    """Set REMOTE_ADDR from CF-Connecting-IP when behind a Cloudflare Tunnel.

    Cloudflare strips any client-supplied CF-Connecting-IP header before
    forwarding, so the value is trustworthy as long as the only path to this
    app is through the tunnel.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            request.META["REMOTE_ADDR"] = cf_ip
        return self.get_response(request)
