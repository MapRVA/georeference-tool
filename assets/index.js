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

// Make Alpine globally available
window.Alpine = Alpine;

// Start Alpine
Alpine.start();

console.log("Vite bundle loaded with Alpine.js, Bootstrap, and Font Awesome");
