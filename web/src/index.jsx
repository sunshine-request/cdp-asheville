import React from "react";
import ReactDOM from "react-dom";
import { App, AppConfigProvider } from "@sunshine-request/cdp-frontend";

import "@sunshine-request/cdp-frontend/dist/index.css";

const config = {
    firebaseConfig: {
        options: {
            projectId: "cdp-asheville-ektqmrjs",
        },
        settings: {},
    },
    municipality: {
        name: "Asheville",
        timeZone: "America/New_York",
        footerLinksSections: [],
    },
    features: {
        // enableClipping: true,
    },
}

ReactDOM.render(
    <div>
        <AppConfigProvider appConfig={config}>
            <App />
        </AppConfigProvider>
    </div>,
    document.getElementById("root")
);