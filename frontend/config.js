const getBackendBaseUrl = () => {
    if (typeof window !== 'undefined') {
        // 0. Stored override in localStorage
        const storedUrl = localStorage.getItem('custom_backend_url') || localStorage.getItem('backend_url');
        if (storedUrl && storedUrl.trim()) {
            return storedUrl.trim().replace(/\/+$/, '');
        }
        // 1. Explicit global runtime override (e.g. injected by environment)
        if (window.__BACKEND_URL__ && typeof window.__BACKEND_URL__ === 'string' && window.__BACKEND_URL__.trim()) {
            return window.__BACKEND_URL__.trim().replace(/\/+$/, '');
        }
        // 2. HTML meta tag configuration (e.g. set at deployment)
        if (typeof document !== 'undefined') {
            const metaTag = document.querySelector('meta[name="backend-url"]');
            if (metaTag && metaTag.content && metaTag.content.trim()) {
                return metaTag.content.trim().replace(/\/+$/, '');
            }
        }
        // 3. Localhost development: Django typically runs on port 8000
        const hostname = window.location.hostname;
        if (hostname === 'localhost' || hostname === '127.0.0.1' || window.location.protocol === 'file:') {
            return 'http://127.0.0.1:8000';
        }
        // 4. Hosted production fallback (same-origin or proxy deployment)
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

    if (path.startsWith('http://') || path.startsWith('https://')) {
        if (path.startsWith('http://127.0.0.1:8000') || path.startsWith('http://localhost:8000')) {
            const backendBase = getBackendBaseUrl();
            const relativePath = path.replace(/^http:\/\/(127\.0\.0\.1|localhost):8000/, '');
            return `${backendBase}${relativePath}`;
        }
        return path;
    }
    
    const backendBase = getBackendBaseUrl();
    
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

