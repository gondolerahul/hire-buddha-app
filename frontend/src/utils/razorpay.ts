/**
 * Razorpay Checkout, loaded the first time a payment starts (FE-22).
 *
 * `checkout.js` used to be a blocking `<script>` in `index.html`, fetched on every
 * page load of every page — including the login form — for a script only the
 * wallet page uses.
 */
const CHECKOUT_URL = 'https://checkout.razorpay.com/v1/checkout.js';

let loading: Promise<any> | null = null;

/** `window.Razorpay`, loading the script once; rejects if it cannot load. */
export function loadRazorpay(): Promise<any> {
    const existing = (window as any).Razorpay;
    if (existing) return Promise.resolve(existing);
    if (!loading) {
        loading = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = CHECKOUT_URL;
            script.async = true;
            script.onload = () => {
                const Razorpay = (window as any).Razorpay;
                if (Razorpay) resolve(Razorpay);
                else reject(new Error('Razorpay Checkout loaded without defining Razorpay'));
            };
            script.onerror = () => {
                loading = null; // let a later attempt retry
                script.remove();
                reject(new Error('Razorpay Checkout could not be loaded'));
            };
            document.head.appendChild(script);
        });
    }
    return loading;
}
