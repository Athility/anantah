const CONFIG = {
    API_BASE_URL: 'http://127.0.0.1:8000/api'
};

let isRefreshingToken = false;
let refreshSubscribers = [];

function subscribeTokenRefresh(cb) {
    refreshSubscribers.push(cb);
}

function onRefreshed(token) {
    refreshSubscribers.map(cb => cb(token));
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

        // If 401 Unauthorized, attempt token refresh unless this request IS login or refresh endpoint
        if (response.status === 401 && !url.includes('/accounts/login/')) {
            const refreshToken = localStorage.getItem('refresh_token') || localStorage.getItem('refreshToken');
            if (!refreshToken) {
                if (typeof clearAuth === 'function') clearAuth();
                return response;
            }

            if (!isRefreshingToken) {
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
                    } else {
                        isRefreshingToken = false;
                        refreshSubscribers = [];
                        if (typeof clearAuth === 'function') clearAuth();
                        return response;
                    }
                } catch (refreshErr) {
                    isRefreshingToken = false;
                    refreshSubscribers = [];
                    if (typeof clearAuth === 'function') clearAuth();
                    return response;
                }
            }

            // Return promise that resolves when refresh is completed
            return new Promise((resolve) => {
                subscribeTokenRefresh((newToken) => {
                    options.headers['Authorization'] = 'Bearer ' + newToken;
                    resolve(fetch(url, options));
                });
            });
        }

        return response;
    } catch (netErr) {
        if (typeof showToastAlert === 'function') {
            showToastAlert('Network connection lost. Please check your internet.', 'error');
        }
        throw netErr;
    }
}

