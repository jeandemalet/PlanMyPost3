# Bug Fix Implementation Plan

## 🔴 Critical Bugs (High Priority - Data Corruption & App Stability)

### 1. Fix Destructive Publication Data Cycle
- [ ] Modify `removeEmptyPublications()` in `public/script.js` to never delete Publication A (index 0)
- [ ] Test publication sequence stability

### 2. Fix BaseComponent Reference Error
- [ ] Reorder script loading in `public/index.html` to load BaseComponent.js first
- [ ] Verify modular architecture initialization works

### 3. Fix Image Dimensions Not Being Saved
- [ ] Update `image-worker.js` to return width and height metadata
- [ ] Verify image dimensions are stored in database

## 🟠 Logical Bugs and Data Inconsistencies

### 4. Standardize "Jour" to "Publication" Naming
- [ ] Update `models/Gallery.js` - rename `nextJourIndex` to `nextPublicationIndex`
- [ ] Update `models/Schedule.js` - standardize `jourLetter` to `publicationLetter`
- [ ] Update all controllers to use consistent naming
- [ ] Update frontend variables (jourFrame → publicationFrame, etc.)

### 5. Fix Admin Panel User Display
- [ ] Update `public/admin.js` to use `user.name` instead of `user.displayName`

## 🟡 Frontend and UI Bugs

### 6. Fix Image Grid Scrolling Issue
- [ ] Add `min-height: 0` to `#imageGridContainer` in `public/style.css`

### 7. Fix CSS Syntax Error
- [ ] Locate and fix missing closing brace for `.ig-feed-item` rule in `public/style.css`

## ✅ Security and Validation Improvements

### 8. Make Deployment Validation Blocking
- [ ] Update `.github/workflows/deploy.yml` to fail on validation errors
- [ ] Remove non-blocking fallbacks

### 9. Add Permission Checks to Zip Export
- [ ] Update `zipExportController.js` to validate job ownership
- [ ] Prevent unauthorized access to export jobs

### 10. Fix Publication Deletion Validation
- [ ] Update `routes/api.js` to use `validatePublicationRoute` instead of `validateImageId`

## Testing and Verification
- [ ] Test publication creation/deletion stability
- [ ] Verify image upload with dimensions
- [ ] Test admin panel functionality
- [ ] Validate deployment pipeline
- [ ] Test zip export security
