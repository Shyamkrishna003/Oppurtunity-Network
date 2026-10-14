import { z } from "zod";

// The site's Content-Security-Policy forbids generating code at run time. Zod would find
// that out by trying, which the browser reports as a violation; tell it not to try.
//
// Imported for its effect, before anything that defines a schema: imports run in order,
// and schemas are built as their modules load.
z.config({ jitless: true });
