/**
 * Anantah Frontend Configuration
 *
 * Architecture:
 * - Frontend: Deployed on Vercel (static SPA).
 * - Backend: Django API running on local PC port 8000, exposed via HTTPS Cloudflare Tunnel.
 * - Production: Browser sends requests directly to the Cloudflare Tunnel URL (e.g. https://api.yourdomain.com or https://*.trycloudflare.com).
 * - Development: Browser connects to http://127.0.0.1:8000 when served on localhost.
 */

// Optional default production backend URL (e.g., 'https://api.yourdomain.com')
// Can also be configured dynamically via <meta name="backend-url" content="..."> in index.html,
// window.__BACKEND_URL__, or localStorage.getItem('custom_backend_url').
const DEFAULT_PRODUCTION_API_URL = '';

const getBackendBaseUrl = () => {
    if (typeof window !== 'undefined') {
        // 1. Explicit global runtime override (injected by script / deployment)
        if (window.__BACKEND_URL__ && typeof window.__BACKEND_URL__ === 'string' && window.__BACKEND_URL__.trim()) {
            return window.__BACKEND_URL__.trim().replace(/\/+$/, '');
        }

        // 2. Developer / tester dynamic override via browser localStorage:
        //    Allows testing quick ephemeral tunnels (e.g., https://xyz.trycloudflare.com) on Vercel instantly without redeploying:
        //    Open DevTools Console -> localStorage.setItem('custom_backend_url', 'https://xyz.trycloudflare.com')
        try {
            const devOverride = localStorage.getItem('custom_backend_url');
            if (devOverride && typeof devOverride === 'string' && devOverride.trim()) {
                return devOverride.trim().replace(/\/+$/, '');
            }
        } catch (e) {
            // LocalStorage might be disabled in private browsing
        }

        // 3. HTML meta tag configuration (e.g. <meta name="backend-url" content="https://api.yourdomain.com">)
        if (typeof document !== 'undefined') {
            const metaTag = document.querySelector('meta[name="backend-url"]');
            if (metaTag && metaTag.content && metaTag.content.trim()) {
                return metaTag.content.trim().replace(/\/+$/, '');
            }
        }

        // 4. Localhost development: Django typically runs on port 8000
        const hostname = window.location.hostname;
        if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0' || window.location.protocol === 'file:') {
            return 'http://127.0.0.1:8000';
        }

        // 5. Configured default production API URL
        if (DEFAULT_PRODUCTION_API_URL && DEFAULT_PRODUCTION_API_URL.trim()) {
            return DEFAULT_PRODUCTION_API_URL.trim().replace(/\/+$/, '');
        }

        // 6. Hosted production warning fallback:
        //    If running on Vercel or a hosted domain with no tunnel configured, log guidance for the developer
        console.warn(
            '[Anantah Config] No backend URL configured for hosted deployment.\n' +
            'Set <meta name="backend-url" content="https://your-tunnel-url"> in index.html,\n' +
            'or run in browser console: localStorage.setItem("custom_backend_url", "https://your-tunnel-url")'
        );
        return window.location.origin;
    }
    return 'http://127.0.0.1:8000';
};

const CONFIG = {
    API_BASE_URL: `${getBackendBaseUrl()}/api`
};

function getMediaUrl(path) {
    if (!path || typeof path !== 'string') return 'anantah_logo.png';
    path = path.trim();
    if (!path) return 'anantah_logo.png';
    
    if (path.startsWith('data:') || path.startsWith('blob:')) {
        return path;
    }

    const backendBase = getBackendBaseUrl();

    if (path.startsWith('http://') || path.startsWith('https://')) {
        // Rewrite localhost or 127.0.0.1 URLs to the configured backend base URL
        // Ensures media works in production even if database or serializer had localhost
        if (path.startsWith('http://127.0.0.1:8000') || path.startsWith('http://localhost:8000')) {
            const relativePath = path.replace(/^http:\/\/(127\.0\.0\.1|localhost):8000/, '');
            return `${backendBase}${relativePath}`;
        }
        return path;
    }
    
    if (path.startsWith('/')) {
        return `${backendBase}${path}`;
    }
    
    if (path.startsWith('media/')) {
        return `${backendBase}/${path}`;
    }

    return path;
}

let isRefreshingToken = false;
let refreshSubscribers = [];

function subscribeTokenRefresh(resolve, reject) {
    refreshSubscribers.push({ resolve, reject });
}

function onRefreshed(token) {
    refreshSubscribers.forEach(({ resolve }) => resolve(token));
    refreshSubscribers = [];
}

function onRefreshError(errorOrResponse) {
    refreshSubscribers.forEach(({ resolve, reject }) => {
        if (errorOrResponse && typeof errorOrResponse.status === 'number') {
            resolve(errorOrResponse);
        } else {
            reject(errorOrResponse || new Error('Token refresh failed'));
        }
    });
    refreshSubscribers = [];
}

async function customFetch(url, options = {}) {
    options.headers = options.headers || {};
    
    // Add default Authorization header if token exists and not manually provided
    const token = localStorage.getItem('access_token') || localStorage.getItem('accessToken');
    if (token && !options.headers['Authorization'] && !options.headers['authorization']) {
        options.headers['Authorization'] = 'Bearer ' + token;
    }

    try {
        let response = await fetch(url, options);

        // If 401 Unauthorized, attempt token refresh unless this request IS login, refresh endpoint, or already retried
        if (response.status === 401 && !url.includes('/accounts/login/') && !options._retry) {
            const refreshToken = localStorage.getItem('refresh_token') || localStorage.getItem('refreshToken');
            if (!refreshToken) {
                if (typeof clearAuth === 'function') clearAuth();
                return response;
            }

            options._retry = true;

            if (isRefreshingToken) {
                // Another request is already refreshing; wait for it
                return new Promise((resolve, reject) => {
                    subscribeTokenRefresh((newToken) => {
                        options.headers['Authorization'] = 'Bearer ' + newToken;
                        resolve(fetch(url, options));
                    }, reject);
                });
            }

            // We are the initiator of the refresh
            isRefreshingToken = true;
            try {
                const refreshRes = await fetch(`${CONFIG.API_BASE_URL}/accounts/login/refresh/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh: refreshToken })
                });

                if (refreshRes.ok) {
                    const refreshData = await refreshRes.json();
                    const newToken = refreshData.access;
                    localStorage.setItem('access_token', newToken);
                    localStorage.setItem('accessToken', newToken);
                    if (refreshData.refresh) {
                        localStorage.setItem('refresh_token', refreshData.refresh);
                        localStorage.setItem('refreshToken', refreshData.refresh);
                    }
                    isRefreshingToken = false;
                    onRefreshed(newToken);

                    // Retry the initiator's request directly with the new token
                    options.headers['Authorization'] = 'Bearer ' + newToken;
                    return fetch(url, options);
                } else {
                    isRefreshingToken = false;
                    onRefreshError(response);
                    if (typeof clearAuth === 'function') clearAuth();
                    return response;
                }
            } catch (refreshErr) {
                isRefreshingToken = false;
                onRefreshError(refreshErr);
                if (typeof clearAuth === 'function') clearAuth();
                return response;
            }
        }

        return response;
    } catch (netErr) {
        if (typeof showToastAlert === 'function') {
            showToastAlert('Network connection lost. Please check your internet.', 'error');
        }
        throw netErr;
    }
}

