
export default function PrivacyPolicy() {
  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold text-text-primary mb-6">Privacy Policy</h1>

      <p className="text-text-secondary text-sm mb-6">
        Last updated: January 2026
      </p>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">What is ContentMind?</h2>
        <p className="text-text-secondary">
          ContentMind is an AI-powered content planning platform that helps users
          plan, organize, generate, and manage social media content, including
          Instagram integrations.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">What Information Do We Collect?</h2>

        <h3 className="text-xl font-medium text-text-primary mb-3">Account Details and Contact Information</h3>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>Email address, provided during signup or login.</li>
          <li>Hashed password, stored securely in our backend database.</li>
        </ul>

        <h3 className="text-xl font-medium text-text-primary mb-3">User-Generated Content and Content Planning Information</h3>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>Content items: titles, text, platform assignments, and performance metrics.</li>
          <li>Content plans and strategy profiles, including niche, topics, goals, and content pillars.</li>
          <li>Media assets uploaded by users (videos, images).</li>
          <li>Memory events and audit trail entries qualifying recommendations.</li>
        </ul>

        <h3 className="text-xl font-medium text-text-primary mb-3">Instagram Account Information</h3>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>
            Instagram account identifiers: account ID, username, account type
            (personal/professional), media count, followers count, follows count,
            and profile picture URL, obtained through the Instagram Graph API
            after user authorization.
          </li>
          <li>
            Instagram access tokens, encrypted at rest using AES-GCM encryption
            with an HKDF-derived key from the
            <code>INSTAGRAM_ENCRYPTION_KEY</code> environment variable. Tokens
            have a 60-day lifetime and are rotated when the user re-authenticates.
          </li>
          <li>
            Scopes granted by the user during the Instagram OAuth consent screen,
            and token expiration information.
          </li>
          <li>
            Imported posts with metadata: caption/title, platform, published_at
            timestamp, Instagram external ID, and URL.
          </li>
          <li>
            Account insights: impressions, reach, profile views, follower count,
            website clicks, and engagement metrics from the Instagram Graph API.
          </li>
          <li>
            Sync job metadata: number of posts examined, posts imported, snapshots
            created, and error categories (if any) from each sync job.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">Why Do We Collect Information and How Is It Used?</h2>
        <p className="text-text-secondary mb-4">
          We collect the above information to provide and improve the ContentMind
          platform, specifically to:
        </p>
        <ul className="list-disc list-inside text-text-secondary space-y-2">
          <li>Authenticate users and provide access to the platform.</li>
          <li>Enable content planning, organization, and generation features, including AI-assisted content creation.</li>
          <li>Support Instagram integration: sync media, import posts, and display performance metrics and account insights.</li>
          <li>Improve the service through usage analytics and metric snapshots.</li>
          <li>Generate strategy recommendations and long-term memory insights.</li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">How Do We Use Instagram Login and API Permissions?</h2>
        <p className="text-text-secondary mb-4">
          ContentMind supports Instagram connection via the official OAuth 2.0 flow
          with Meta. When a user clicks "Connect Instagram," they are redirected to
          Meta's authorization screen where they grant specific permissions. The
          permissions granted determine what Instagram data the application can
          access and include: <em>basic profile information, media content, and
          insights.</em> After the user authorizes the connection, ContentMind
          exchanges the authorization code for a long-lived access token (60-day
          lifetime), which is encrypted at rest and stored alongside the associated
          Instagram account ID, username, and scopes. This token is used to make
          Graph API calls on the user's behalf to synchronize media, import posts,
          and fetch account insights for display in the ContentMind dashboard. Users
          may disconnect their Instagram account at any time, which revokes the token
          and removes the stored connection data.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">How Are Instagram Access Tokens and Credentials Protected?</h2>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>
            Access tokens are encrypted at rest using AES-GCM encryption. The
            encryption key is derived from the
            <code>INSTAGRAM_ENCRYPTION_KEY</code> environment variable via HKDF.
          </li>
          <li>
            OAuth state is signed with HMAC-SHA256 and has a 10-minute expiry to
            prevent cross-site request forgery (CSRF) across user accounts.
          </li>
          <li>
            JWT authentication tokens have a 24-hour (1440 minute) expiration and are
            attached to API requests via an interceptor.</li>
          <li>
            CORS is configured to allow only the registered frontend and backend
            origins.</li>
          <li>
            Users can disconnect their Instagram account at any time, which
            immediately revokes the stored token and removes it from the database.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">Which Third-Party Services Receive or Process Information?</h2>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>
            <strong>Meta (Instagram Graph API):</strong> When a user connects their
            Instagram account, the following data is shared with Meta: Instagram user
            ID, profile information, media metadata, and insights. This data is
            processed per Meta's Data Policy. The Instagram access token is used to
            make API calls on the user's behalf.
          </li>
          <li>
            <strong>Google Gemini:</strong> When the
            <code>LLM_PROVIDER=gemini</code> configuration is active (which is the
            production default), content generation and strategy recommendations are
            processed by the Gemini API (<code>gemini-3.8-flash</code>). The input
            may include user-provided content strategy data and platform-specific
            parameters. The output (generated content, recommendations) is returned to
            ContentMind and displayed to the user.
          </li>
          <li>
            <strong>OpenAI-compatible providers:</strong> When configured as fallback
            (e.g., Groq, OpenRouter, Together, DeepInfra, Ollama, vLLM), LLM
            requests may be sent to these providers' endpoints. The data sent
            typically includes the conversation history and generation parameters.
          </li>
          <li>
            <strong>Render:</strong> The backend FastAPI service is hosted on Render
            in the United States.
          </li>
          <li>
            <strong>Cloudflare Workers:</strong> The frontend is served from
            Cloudflare Workers at
            <code>content-mind.dattarishikesh2498.workers.dev</code>.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">Data Retention and Deletion Practices</h2>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>
            User account data (email, hashed password) is retained for the duration
            of the active account. Users may request account deletion, which removes
            their user record and all associated data.
          </li>
          <li>
            Instagram connection data (account ID, username, encrypted token,
            scopes, metadata) is retained for as long as the user maintains the
            connected Instagram account. Disconnecting removes the encrypted token
            and all associated sync data from the database.
          </li>
          <li>
            Metric snapshots and performance data are retained indefinitely while
            the account is active, as they inform strategy recommendations and
            long-term memory.
          </li>
          <li>
            Instagram access tokens have a 60-day lifetime. When a token expires,
            the user must re-authenticate to restore Instagram connectivity.
          </li>
          <li>
            Users may request deletion of their account and all associated data by
            contacting the support team. See the "Contact" section below.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">How Can Users Disconnect Instagram and Request Data Deletion?</h2>
        <p className="text-text-secondary mb-4">
          To disconnect an Instagram account, navigate to the Instagram page within
          ContentMind and click the "Disconnect" button next to the connected account.
          This action revokes the stored access token, removes the Instagram
          connection record from the database, and stops any ongoing or future sync
          jobs. The user's content data already imported to ContentMind is not removed
          by disconnecting; only the connection and credentials are deleted.
        </p>
        <p className="text-text-secondary mb-4">
          To request full account deletion, users should contact the support team.
          Upon verified request, the user's account, all content items, plans, media
          assets, Instagram connections, and associated metadata will be permanently
          removed from the database.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">Security Practices</h2>
        <p className="text-text-secondary mb-4">
          We implement the following security measures:
        </p>
        <ul className="list-disc list-inside text-text-secondary space-y-1">
          <li>Passwords are hashed using PBKDF2-SHA256 in the backend.</li>
          <li>Instagram access tokens are encrypted at rest using AES-GCM.</li>
          <li>JWT tokens are signed with HS256 and have short expirations (24 hours).</li>
          <li>OAuth state tokens are HMAC-signed with a 10-minute expiry.</li>
          <li>CORS is restricted to registered origins only.</li>
          <li>Backend infrastructure is hosted on Render.</li>
          <li>Frontend is served via Cloudflare Workers.</li>
        </ul>
        <p className="text-text-secondary mt-2">
          Please note: No security system can be guaranteed to be impenetrant.
          While we take reasonable precautions, we cannot guarantee absolute
          security. Users should use strong, unique passwords and remain aware of
          the inherent risks of online data storage.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">Children's Privacy</h2>
        <p className="text-text-secondary">
          ContentMind is not directed to children under 13 years of age. We do not
          knowingly collect personal data from children under 13. If you are a
          parent or guardian and believe your child has provided us with data, please
          contact us so we can take appropriate action.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">International Data Processing</h2>
        <p className="text-text-secondary">
          The ContentMind backend is hosted in the United States on Render. Instagram
          data, once connected, may be processed globally per Meta's Data Policy,
          including transfers to and storage in the United States and other
          jurisdictions. LLM processing may occur on infrastructure provided by
          third-party AI service providers, which may be located outside the user's
          country of residence.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">How Do We Communicate Policy Updates?</h2>
        <p className="text-text-secondary">
          Users will be notified of any material changes to this Privacy Policy via
          email or in-app notification. Users are encouraged to review this page
          periodically. Continued use of ContentMind after a policy change
          constitutes acceptance of the updated terms.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-2xl font-semibold text-text-primary mb-4">Contact</h2>
        <p className="text-text-secondary">
          If you have questions about this Privacy Policy, or if you would like to
          request access to, correction of, or deletion of your personal data, please
          contact us at
          <a href="mailto:contentmind09@gmail.com" className="underline">
            contentmind09@gmail.com
          </a>.
          Please specify "Privacy Policy Inquiry" in the subject line.
        </p>
        <div className="mt-8 pt-8 border-t border-border-light text-center text-sm text-text-tertiary dark:border-border-medium dark:text-bg-secondary/50">
          <a href="/terms-of-service" className="underline font-medium text-primary-600 dark:text-primary-400">
            Terms of Service
          </a>
          <span className="mx-4">|</span>
          <a href="/" className="underline font-medium text-primary-600 dark:text-primary-400">
            Back to ContentMind
          </a>
        </div>
      </section>
    </div>
  )
}
