import Alpine from "alpinejs";

// Import our custom styles (includes Bootstrap via Sass)
import "./scss/styles.scss";

// Import Bootstrap JS
import * as bootstrap from "bootstrap";

// Import global component styles
import "./styles/components/image-cards.css";

// Import global utilities
import "./js/components/notifications.js";

// Import Font Awesome core
import { library, dom } from "@fortawesome/fontawesome-svg-core";

// Import only the specific icons we use (much smaller bundle)
import {
  faAlignLeft,
  faArchive,
  faArrowDown,
  faArrowLeft,
  faBan,
  faCalendar,
  faCalendarDays,
  faChartBar,
  faChartLine,
  faChartPie,
  faCheck,
  faCheckCircle,
  faChevronDown,
  faChevronLeft,
  faChevronRight,
  faChevronUp,
  faCircleXmark,
  faClock,
  faCloudUploadAlt,
  faCog,
  faComment,
  faCompass,
  faCopy,
  faCrosshairs,
  faDrawPolygon,
  faEdit,
  faExclamationCircle,
  faExclamationTriangle,
  faExternalLinkAlt,
  faEye,
  faFilter,
  faFire,
  faFolder,
  faFolderOpen,
  faFont,
  faForward,
  faGlobe,
  faGripVertical,
  faHeading,
  faHistory,
  faHome,
  faImage,
  faImages,
  faInbox,
  faInfoCircle,
  faLayerGroup,
  faLock,
  faMagnifyingGlassPlus,
  faMap,
  faMapMarkedAlt,
  faMapMarkerAlt,
  faMapPin,
  faPhotoVideo,
  faPlane,
  faPlus,
  faQuestion,
  faRandom,
  faRocket,
  faSatellite,
  faSave,
  faSearch,
  faSearchLocation,
  faShuffle,
  faSignal,
  faSignInAlt,
  faSignOutAlt,
  faSpinner,
  faSquareCheck,
  faSquareUpRight,
  faStar,
  faSyncAlt,
  faTag,
  faTimes,
  faTrash,
  faUndo,
  faUser,
  faUserCheck,
  faUserCircle,
  faUsers,
} from "@fortawesome/free-solid-svg-icons";

// Add all icons to the library
library.add(
  faAlignLeft,
  faArchive,
  faArrowDown,
  faArrowLeft,
  faBan,
  faCalendar,
  faCalendarDays,
  faChartBar,
  faChartLine,
  faChartPie,
  faCheck,
  faCheckCircle,
  faChevronDown,
  faChevronLeft,
  faChevronRight,
  faChevronUp,
  faCircleXmark,
  faClock,
  faCloudUploadAlt,
  faCog,
  faComment,
  faCompass,
  faCopy,
  faCrosshairs,
  faDrawPolygon,
  faEdit,
  faExclamationCircle,
  faExclamationTriangle,
  faExternalLinkAlt,
  faEye,
  faFilter,
  faFire,
  faFolder,
  faFolderOpen,
  faFont,
  faForward,
  faGlobe,
  faGripVertical,
  faHeading,
  faHistory,
  faHome,
  faImage,
  faImages,
  faInbox,
  faInfoCircle,
  faLayerGroup,
  faLock,
  faMagnifyingGlassPlus,
  faMap,
  faMapMarkedAlt,
  faMapMarkerAlt,
  faMapPin,
  faPhotoVideo,
  faPlane,
  faPlus,
  faQuestion,
  faRandom,
  faRocket,
  faSatellite,
  faSave,
  faSearch,
  faSearchLocation,
  faShuffle,
  faSignal,
  faSignInAlt,
  faSignOutAlt,
  faSpinner,
  faSquareCheck,
  faSquareUpRight,
  faStar,
  faSyncAlt,
  faTag,
  faTimes,
  faTrash,
  faUndo,
  faUser,
  faUserCheck,
  faUserCircle,
  faUsers,
);

// Replace any existing <i> tags with <svg> and set up a MutationObserver to
// continue doing this as the DOM changes.
dom.watch();

// Make Bootstrap globally available
window.bootstrap = bootstrap;

// Make Alpine globally available for page scripts to register components
window.Alpine = Alpine;

/**
 * Global CSRF token utility - available throughout the app
 */
window.getCsrfToken = function () {
  // First try to get from a form input
  const inputToken = document.querySelector(
    "[name=csrfmiddlewaretoken]",
  )?.value;
  if (inputToken) return inputToken;

  // Fall back to reading from cookie
  const name = "csrftoken";
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
};

// Start Alpine on DOMContentLoaded after all page scripts have registered their components.
// This ensures the load order is:
// 1. index.js loads and sets window.Alpine
// 2. Page-specific scripts load and call Alpine.data() to register components
// 3. DOMContentLoaded fires and Alpine.start() initializes all components
document.addEventListener("DOMContentLoaded", () => {
  Alpine.start();
});

console.log("Vite bundle loaded with Alpine.js, Bootstrap, and Font Awesome");
