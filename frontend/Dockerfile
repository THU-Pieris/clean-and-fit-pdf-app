FROM nginx:1.29-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/styles.css /usr/share/nginx/html/styles.css
COPY frontend/app.js /usr/share/nginx/html/app.js

# A new asset URL for each content change prevents old browser/proxy caches from
# combining a new document with the previous release's CSS or JavaScript.
RUN set -eu; \
    cd /usr/share/nginx/html; \
    mkdir -p assets; \
    css_hash=$(sha256sum styles.css | cut -c1-16); \
    js_hash=$(sha256sum app.js | cut -c1-16); \
    mv styles.css "assets/styles.${css_hash}.css"; \
    mv app.js "assets/app.${js_hash}.js"; \
    sed -i \
      -e "s|./styles.css|./assets/styles.${css_hash}.css|g" \
      -e "s|./app.js|./assets/app.${js_hash}.js|g" \
      index.html
