/** Key typing: `t("nav.orders")` with a typo is a compile error, checked by the
 * `tsc -b` half of `npm run build`. JSON imports keep literal *keys* but widen
 * values to `string`, so interpolation params are NOT compile-checked — the
 * placeholder checks in src/i18n/catalogue.test.ts are the control for that. */
import type catalogue from "./catalogues/en-AU.json";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: typeof catalogue };
    returnNull: false;
  }
}
