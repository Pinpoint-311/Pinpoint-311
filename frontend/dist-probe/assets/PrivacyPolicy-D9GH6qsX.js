import{u as n,j as e,ai as c,a4 as l,N as m}from"./main-DHi_zKps.js";import"./preload-helper-ckwbz45p.js";import"./backend-D5a3Te7D.js";const u=`
## Information We Collect

When you submit a service request, we collect only the information necessary to process and respond to your request:

- **Contact Information**: Name, email address, and/or phone number (email is required for all submissions)
- **Location Data**: Address or geographic coordinates related to your service request
- **Request Details**: Description of the issue, photos, and any additional context you provide
- **Technical Data**: Browser type, device information, and IP address for security purposes

### Why Email is Required

An email address is required for all service requests to:
- Send you status updates on your request
- Request additional information if needed
- Notify you when your issue has been resolved
- Maintain accountability and prevent abuse of the system

## How We Use Your Information

Your information is used exclusively for municipal service purposes:

- Processing and tracking your service requests
- Routing requests to the appropriate department
- Communicating with you about your request status
- Improving our services based on aggregate data
- Complying with public records laws

**We do not:**
- Sell your personal information
- Use your information for marketing purposes
- Share your information with third parties for commercial purposes

## Information Sharing

We may share your information with:

- **Municipal Departments**: Staff members responsible for addressing your service request
- **Contractors**: Third-party vendors working on behalf of the municipality
- **Legal Requirements**: When required by law, court order, or public records request

## Data Retention

Your service request data is retained in accordance with applicable state public records retention schedules. Personal identifying information may be anonymized after the required retention period.

## Your Rights

You have the right to:
- Request access to your personal information
- Request correction of inaccurate information
- Submit requests anonymously (for most request types)
- Contact us with privacy concerns

## Security

We implement appropriate technical and organizational measures to protect your personal information, including encryption of data in transit and at rest.

## Contact Us

For privacy-related questions or concerns, please contact your municipal clerk or the department of administration.

---

*This privacy policy applies to service requests submitted through the 311 portal. For the municipality's general privacy policy, please visit the main municipal website.*
`;function y(){const{settings:s}=n(),i=(s==null?void 0:s.privacy_policy)||u,o=(s==null?void 0:s.township_name)||"Your Municipality";return e.jsxs("div",{className:"min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900",children:[e.jsx("header",{className:"glass-sidebar border-b border-white/10",children:e.jsxs("div",{className:"max-w-4xl mx-auto px-4 py-4 flex items-center gap-4",children:[e.jsx(c,{to:"/",className:"p-2 rounded-lg hover:bg-white/10 transition-colors","aria-label":"Back to home",children:e.jsx(l,{className:"w-5 h-5 text-white/70"})}),e.jsxs("div",{className:"flex items-center gap-3",children:[e.jsx("div",{className:"w-10 h-10 rounded-xl bg-primary-500/20 flex items-center justify-center",children:e.jsx(m,{className:"w-5 h-5 text-primary-400"})}),e.jsxs("div",{children:[e.jsx("h1",{className:"text-xl font-bold text-white",children:"Privacy Policy"}),e.jsxs("p",{className:"text-sm text-white/50",children:[o," 311 Service"]})]})]})]})}),e.jsxs("main",{className:"max-w-4xl mx-auto px-4 py-8",children:[e.jsx("div",{className:"glass-card rounded-2xl p-8",children:e.jsx("div",{className:"prose prose-invert prose-sm max-w-none",children:i.split(`
`).map((t,r)=>{if(t.startsWith("## "))return e.jsx("h2",{className:"text-xl font-bold text-white mt-8 mb-4 first:mt-0",children:t.replace("## ","")},r);if(t.startsWith("### "))return e.jsx("h3",{className:"text-lg font-semibold text-white/90 mt-6 mb-3",children:t.replace("### ","")},r);if(t.startsWith("- **")){const a=t.match(/- \*\*(.+?)\*\*: (.+)/);if(a)return e.jsxs("li",{className:"text-white/70 ml-4 my-1",children:[e.jsxs("strong",{className:"text-white",children:[a[1],":"]})," ",a[2]]},r)}return t.startsWith("- ")?e.jsx("li",{className:"text-white/70 ml-4 my-1",children:t.replace("- ","")},r):t.startsWith("**")&&t.endsWith("**")?e.jsx("p",{className:"text-white font-semibold my-2",children:t.replace(/\*\*/g,"")},r):t.startsWith("*")&&t.endsWith("*")?e.jsx("p",{className:"text-white/50 italic text-sm my-4",children:t.replace(/\*/g,"")},r):t==="---"?e.jsx("hr",{className:"border-white/10 my-8"},r):t.trim()?e.jsx("p",{className:"text-white/70 my-3",children:t},r):null})})}),e.jsxs("p",{className:"text-center text-white/30 text-sm mt-8",children:["Last updated: ",new Date().toLocaleDateString()]})]})]})}export{y as default};
