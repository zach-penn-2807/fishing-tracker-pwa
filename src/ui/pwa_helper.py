import streamlit as st
import streamlit.components.v1 as components


def inject_pwa_head() -> None:
    """Inject PWA manifest, Apple Home Screen tags, and a live online/offline banner."""
    components.html(
        """
        <script>
        const parentDoc = window.parent.document;
        if (!parentDoc.querySelector('link[rel="manifest"]')) {
            const tags = [
                { tag: 'link', rel: 'manifest', href: '/app/static/manifest.json' },
                { tag: 'link', rel: 'apple-touch-icon', href: '/app/static/icon.svg' },
                { tag: 'meta', name: 'apple-mobile-web-app-capable', content: 'yes' },
                { tag: 'meta', name: 'apple-mobile-web-app-status-bar-style', content: 'default' },
                { tag: 'meta', name: 'apple-mobile-web-app-title', content: 'Catch Log' }
            ];
            tags.forEach(t => {
                const el = parentDoc.createElement(t.tag);
                Object.entries(t).forEach(([k, v]) => { if (k !== 'tag') el.setAttribute(k, v); });
                parentDoc.head.appendChild(el);
            });
        }
        </script>
        """,
        height=0,
    )

    # Live connection banner so Dad knows if signal drops before tapping Log Catch
    components.html(
        """
        <div id="net-status" style="font-family:sans-serif;font-size:13px;font-weight:600;
             padding:6px 10px;border-radius:8px;text-align:center;"></div>
        <script>
        const box = document.getElementById('net-status');
        function updateStatus() {
            if (navigator.onLine) {
                box.style.background = '#E6EFEA';
                box.style.color = '#1B7F5C';
                box.textContent = '● Connected — Ready to Log';
            } else {
                box.style.background = '#FDECEC';
                box.style.color = '#B42318';
                box.textContent = '⚠ Offline — Keep screen open until signal returns to save';
            }
        }
        window.addEventListener('online', updateStatus);
        window.addEventListener('offline', updateStatus);
        updateStatus();
        </script>
        """,
        height=38,
    )