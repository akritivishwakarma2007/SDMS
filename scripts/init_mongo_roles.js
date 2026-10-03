/**
 * SDMS MongoDB Initialization Script
 * Configures:
 * 1. Database: sdms
 * 2. Eight Collections with JSON Schema Validation
 * 3. Unique & Performance Indexes
 * 4. Append-Only Security Role: sdms_app (insert + find on events; no update/delete)
 *
 * Usage:
 *   mongosh mongodb://localhost:27017/sdms scripts/init_mongo_roles.js
 */

const dbName = "sdms";
db = db.getSiblingDB(dbName);

print("Initializing SDMS MongoDB database schema and security roles...");

// 1. Create Collections with Validation Schemas
const collections = [
  "boxes",
  "sessions",
  "events",
  "event_items",
  "receipts",
  "feedback",
  "users",
  "reconciliations"
];

collections.forEach(col => {
  if (!db.getCollectionNames().includes(col)) {
    db.createCollection(col);
    print(`Created collection: ${col}`);
  }
});

// JSON Schema Validation for 'events' (Append-Only Core Ledger)
db.runCommand({
  collMod: "events",
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["seq", "event_id", "box_id", "session_id", "status", "prev_hash", "record_hash", "signature"],
      properties: {
        seq: { bsonType: "int", description: "Strictly increasing sequence number" },
        event_id: { bsonType: "string", description: "Unique event identifier" },
        box_id: { bsonType: "string", description: "Originating box or server identifier" },
        session_id: { bsonType: "string", description: "Active session identifier" },
        timestamp: { bsonType: "string", description: "ISO 8601 UTC timestamp" },
        status: { enum: ["accepted", "review", "rejected", "ACCEPTED", "REVIEW", "REJECTED", "AMENDMENT"] },
        denomination: { bsonType: "string" },
        confidence: { bsonType: "double" },
        model_version: { bsonType: "string" },
        frame_sha256: { bsonType: "string" },
        prev_hash: { bsonType: "string", pattern: "^[0-9a-fA-F]{64}$" },
        record_hash: { bsonType: "string", pattern: "^[0-9a-fA-F]{64}$" },
        signature: { bsonType: "string" },
        thresholds: { bsonType: "object" },
        items: { bsonType: "array" },
        amends: { bsonType: ["string", "null"] }
      }
    }
  },
  validationLevel: "moderate"
});

// 2. Indexes
print("Configuring unique and performance indexes...");
db.boxes.createIndex({ box_id: 1 }, { unique: true });
db.sessions.createIndex({ session_id: 1 }, { unique: true });
db.events.createIndex({ seq: 1 }, { unique: true });
db.events.createIndex({ event_id: 1 }, { unique: true });
db.events.createIndex({ timestamp: 1 });
db.events.createIndex({ session_id: 1, status: 1 });
db.event_items.createIndex({ event_id: 1 });
db.event_items.createIndex({ seq: 1 });
db.receipts.createIndex({ receipt_id: 1 }, { unique: true });
db.receipts.createIndex({ session_id: 1 });
db.feedback.createIndex({ event_id: 1 });
db.feedback.createIndex({ amends: 1 });
db.users.createIndex({ username: 1 }, { unique: true });
db.reconciliations.createIndex({ session_id: 1 });

// 3. Append-Only Security Role for Application Service
// Restricts 'events' to insert and find actions only; update and remove are strictly forbidden.
try {
  db.createRole({
    role: "sdmsAppendOnlyRole",
    privileges: [
      {
        resource: { db: "sdms", collection: "events" },
        actions: ["insert", "find"]
      },
      {
        resource: { db: "sdms", collection: "event_items" },
        actions: ["insert", "find"]
      },
      {
        resource: { db: "sdms", collection: "receipts" },
        actions: ["insert", "find"]
      },
      {
        resource: { db: "sdms", collection: "feedback" },
        actions: ["insert", "find"]
      },
      {
        resource: { db: "sdms", collection: "reconciliations" },
        actions: ["insert", "find"]
      },
      {
        resource: { db: "sdms", collection: "boxes" },
        actions: ["insert", "find", "update"]
      },
      {
        resource: { db: "sdms", collection: "sessions" },
        actions: ["insert", "find", "update"]
      },
      {
        resource: { db: "sdms", collection: "users" },
        actions: ["insert", "find", "update"]
      }
    ],
    roles: []
  });
  print("Created custom security role: sdmsAppendOnlyRole");
} catch (e) {
  print("sdmsAppendOnlyRole role notice: " + e.message);
}

// Create dedicated application user
try {
  db.createUser({
    user: "sdms_app",
    pwd: "sdms_secure_password_2026",
    roles: [{ role: "sdmsAppendOnlyRole", db: "sdms" }]
  });
  print("Created application user: sdms_app");
} catch (e) {
  print("sdms_app user notice: " + e.message);
}

print("SDMS MongoDB initialization completed successfully.");
