
/**
 * Utility functions for Quick Order (QO) form tests.
 * Includes date calculations, string generation utilities, and predefined field values.
 *
 * Available Outputs:
 * - calculateDueDate(days: number): string
 *   Calculates a future date by adding a specified number of weekdays to today.
 *
 * - calculateStartDate(): string
 *   Calculates the start date, which is two weeks from today, skipping weekends.
 *
 * - calculateEndDate(): string
 *   Calculates the end date, which is three months from today.
 *
 * - generateRandomWords(count: number): string
 *   Generates a random sequence of words.
 *
 * - generateRandomISCI(): string
 *   Generates a random ISCI code (e.g., ABCD-1234).
 *
 * - generateRandomDigits(length: number): string
 *   Generates a random sequence of digits.
 *
 * - generateRandomSpotTitle(): string
 *   Generates a random Spot Title consisting of an adverb, adjective, and noun.
 *
 * - demoScripts: { demo30sScript: string, demo60sScript: string }
 *   Predefined demo scripts for 30s and 60s spots.
 *
 * - demoNotes: {
 *     prodNotes: string,
 *     digitalNotes: string,
 *     trafficNotes: string,
 *     blogNotes: string,
 *     creativeNotes: string,
 *     tagCopy: string
 *   }
 *   Predefined notes for production, digital, traffic, blog, creative, and tag copy fields.
 */

/**
 * Snap a Date forward to the next weekday. Idempotent for Mon–Fri.
 * The QO due-date picker disables weekend day cells (`.p-disabled`),
 * so any generated due/start date MUST land on a weekday or the
 * `selectDateViaPicker` helper throws "day cell not found".
 */
function snapToWeekday(d: Date): Date {
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() + 1);
  }
  return d;
}

/**
 * Calculate a future date representing the Due Date.
 * Matches the legacy AHK script: Wide mapping to ensure safe lead times.
 * Weekend results snap forward to Monday — the picker disables Sat/Sun.
 * @returns {string} - The calculated date in MM/DD/YYYY format.
 */
export function calculateDueDate(legacyDays?: number): string {
  const today = new Date();
  const todayName = today.toLocaleDateString('en-US', { weekday: 'long' });
  let addMe = 7;

  if (todayName === 'Thursday') {
    addMe = 11;
  } else if (todayName === 'Friday') {
    addMe = 10;
  }

  today.setDate(today.getDate() + addMe);
  snapToWeekday(today);

  return today.toLocaleDateString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

/**
 * Calculate a future Date representing the Due Date WITH time.
 * Used for ad types that include a time component on the due date
 * (e.g., TV Ad). Returns a JS Date object set to now + 90 minutes.
 *
 * @returns {Date} - A Date object 90 minutes from now.
 */
export function calculateDueDateTime(): Date {
  const dt = new Date();
  // Add 3 weekdays (skipping Saturday and Sunday) to ensure the date is selectable and satisfies lead time rules
  let added = 0;
  while (added < 3) {
    dt.setDate(dt.getDate() + 1);
    if (dt.getDay() !== 0 && dt.getDay() !== 6) {
      added++;
    }
  }
  dt.setMinutes(dt.getMinutes() + 90);
  return dt;
}

/**
 * Calculate the start date, matching the AHK script for a safe 2-week gap.
 *
 * For TV Ad (Open submit) forms, the application enforces Start Date ≥ Due Date + 14 days.
 * Pass the `dueDate` parameter (the actual Date object used for the due date) so the start
 * date is computed from the due date rather than today, preventing validation rejections.
 *
 * @param dueDate - Optional Due Date to compute from. Defaults to today.
 * @returns {string} - The calculated start date in MM/DD/YYYY format.
 */
export function calculateStartDate(dueDate?: Date): string {
  const base = dueDate ? new Date(dueDate) : new Date();
  const baseName = base.toLocaleDateString('en-US', { weekday: 'long' });
  let addMe = 14;

  if (baseName === 'Thursday') {
    addMe = 22;
  } else if (baseName === 'Friday') {
    addMe = 20;
  }

  base.setDate(base.getDate() + addMe);
  snapToWeekday(base);

  return base.toLocaleDateString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

/**
 * Calculate the end date, matching the AHK script for a safe 3-month gap.
 * Weekend results snap forward to Monday — the picker disables Sat/Sun.
 * @returns {string} - The calculated end date in MM/DD/YYYY format.
 */
export function calculateEndDate(): string {
  const today = new Date();
  const todayName = today.toLocaleDateString('en-US', { weekday: 'long' });
  let addMe = 90;

  if (todayName === 'Thursday') {
    addMe = 94;
  } else if (todayName === 'Friday') {
    addMe = 93;
  }

  today.setDate(today.getDate() + addMe);
  snapToWeekday(today);

  return today.toLocaleDateString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

/**
 * Generate a random sequence of words.
 * @param {number} count - Number of words to generate.
 * @returns {string} - A string containing the generated words.
 */
export function generateRandomWords(count: number): string {
  const words = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon', 'Zeta', 'Eta', 'Theta', 'Iota', 'Kappa'];
  let result = '';

  for (let i = 0; i < count; i++) {
    const randomIndex = Math.floor(Math.random() * words.length);
    result += words[randomIndex] + (i < count - 1 ? ' ' : '');
  }

  return result;
}

/**
 * Generate a random ISCI code (e.g., ABCD-1234).
 * @returns {string} - The generated ISCI code.
 */
export function generateRandomISCI(): string {
  const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const randomLetters = Array.from({ length: 4 }, () => letters[Math.floor(Math.random() * letters.length)]).join('');
  const randomNumbers = Math.floor(1000 + Math.random() * 9000); // Random 4-digit number

  return `${randomLetters}-${randomNumbers}`;
}

/**
 * Generate a random sequence of digits.
 * @param {number} length - Number of digits to generate.
 * @returns {string} - The generated sequence of digits.
 */
export function generateRandomDigits(length: number): string {
  let result = '';
  for (let i = 0; i < length; i++) {
    result += Math.floor(Math.random() * 10).toString();
  }
  return result;
}

/**
 * Generate a random 5-digit contract number.
 * @returns {string} - The generated contract number.
 */
export function generateRandomContractNumber(): string {
  return generateRandomDigits(5);
}

/**
 * Generate a random 4-digit cart ID to avoid duplicate warnings.
 * Cart IDs must be unique across the system.
 * @returns {string} - The generated cart ID.
 */
export function generateRandomCartId(): string {
  // Generate 4-digit random number (1000-9999 range for no leading zeros)
  return String(Math.floor(1000 + Math.random() * 9000));
}

/**
 * Generate a random Spot Title consisting of an adverb, adjective, and noun.
 * Uses inline word lists for zero external dependencies.
 * @returns {string} - The generated Spot Title.
 */
export function generateRandomSpotTitle(): string {
  const adverbs = ['BOLDLY', 'QUICKLY', 'BRIGHTLY', 'CLEARLY', 'DEEPLY', 'EAGERLY', 'FIERCELY', 'GENTLY', 'HIGHLY', 'JUSTLY', 'KEENLY', 'LARGELY', 'MERELY', 'NEATLY', 'OVERLY', 'PURELY', 'RARELY', 'SIMPLY', 'TRULY', 'VASTLY'];
  const adjectives = ['BRAVE', 'CALM', 'DARK', 'EAGER', 'FAIR', 'GRAND', 'HAPPY', 'IDEAL', 'KEEN', 'LUSH', 'MAJOR', 'NOBLE', 'OPEN', 'PRIME', 'QUICK', 'RAPID', 'SHARP', 'TIDAL', 'ULTRA', 'VIVID'];
  const nouns = ['STORM', 'RIVER', 'FLAME', 'CLOUD', 'STONE', 'TOWER', 'EAGLE', 'HAVEN', 'LIGHT', 'RIDGE', 'FORGE', 'PULSE', 'CREST', 'BLOOM', 'DRIFT', 'SPARK', 'ATLAS', 'PRISM', 'GRAIN', 'ORBIT'];

  const pick = (arr: string[]) => arr[Math.floor(Math.random() * arr.length)];
  return `${pick(adverbs)} ${pick(adjectives)} ${pick(nouns)}`;
}


/**
 * Returns a unique client name by appending a random 4-digit number.
 * 
 * @returns {string} - The unique client name.
 */
export function generateUniqueClientName(): string {
  return `Test Client ${generateRandomDigits(4)}`;
}

// Array of valid, business-like fake clients sourced from the AHK helper script.
export const validFakeClients = [
  "A Fridge Too Far Used Appliances",
  "A Site for Sore Thighs - Massage Therapy",
  "A Small Price Toupee - Discount Hair Pieces",
  "A1A Car Wash",
  "Abstergo",
  "Accurate Calendars",
  "ACE Chemicals",
  "ACME Rocket Co.",
  "Albuquerque Isotypes",
  "All Food",
  "Amaya",
  "Aperture Science",
  "Apollo Candy Company",
  "Arasaka",
  "Arch Motorcycle",
  "Assan Motor Company",
  "Auntie Cleo's",
  "Aviato",
  "Baby Got Back Problems Physical Therapy",
  "Bachmanity Capital",
  "Bad Wolf Corporation",
  "Bada Bing!",
  "Bath Sheet Crazy",
  "Bend It Like Bedpan - Medical Supplies",
  "Bend It Like Bedpan Medical Supplies",
  "Betty's Machetes",
  "Bidets and Confused",
  "BiffCo Enterprises",
  "Big Kahuna Burger",
  "Binford Tools",
  "Blood Bath and Beyond",
  "Blue Sun",
  "Bluth Company",
  "Bob Loblaw -  Attorney At Law",
  "Body by Trey",
  "Bowl-a-rama",
  "Brawndo",
  "Bream Hall",
  "Brooklyn Barista",
  "Broseph Ale",
  "Bubba Gump Shrimp Co.",
  "Buck-A-Slice",
  "Burns Industries",
  "Burrito XXL",
  "Bushwood Country Club",
  "Buy and Large Corporation",
  "C7 Aerospace Division",
  "Caboose Kabob",
  "Callister Inc",
  "Cardiff Electric",
  "Carl's Pre-Owned Indoor Outhouses",
  "Castlerock City Council",
  "Cat-Like Refluxes - Feline Gastoenterologist",
  "Central Perk",
  "Ceres Mining and Tech University",
  "Chalmskinn Productions",
  "Chatswin City Council",
  "Cheers",
  "Chester's Mill Tourism",
  "Chevillon",
  "CHOAM",
  "Chromanticore",
  "Cirrus Cola",
  "City of Smallville",
  "Clampett Oil",
  "Cluckin Chicken",
  "Committee to Re-Elect Frank Underwood",
  "Conglom-O",
  "ConHugeCo",
  "Corley Motors",
  "CPM Security Corporation",
  "Crimson Permanent Assurance",
  "Cut Me Some Slacks",
  "Cyberdyne Systems Corporation",
  "d'Anconia Copper",
  "Daily Grind",
  "Daily Planet",
  "Delamain",
  "Delos",
  "Dewey,  Cheatum,  & Howe,  LLP",
  "Dinkelstein Kerman's Construction Emporium",
  "Don't Go There: Cautionary Sign Store",
  "Double R Diner",
  "Dr. Gordon Freeman",
  "Dr. Lawrence Gordon",
  "Dr. Van Nostrom",
  "Dr. Zoidberg",
  "Duff Beer",
  "Dunder Mifflin Paper Company,  Inc.",
  "EEZYBEEF",
  "Emerson Cod P.I.",
  "Ewing Oil",
  "Exterimental Engineering Group",
  "Fake It Till Your Makeup",
  "Fiber Now!",
  "Fisher and Diaz Funeral Home",
  "Flip Your Wig - Reversible Hairpieces",
  "FLOOYD Dynamics Research Labs",
  "Fromage-inary Friends Cheese Shop",
  "Fudge 'N Stuff",
  "Fuyutsuki Electronics",
  "Galaxy News Radio",
  "Gekko and Co.",
  "Genco Pura Olive Oil Company",
  "Globex Corporation",
  "Golden Moth Chemical",
  "Goliath National Bank",
  "Goliath National Products",
  "Good Burger",
  "Goodsprings General Store",
  "Grace Mercy West Hospital",
  "Greendale Community College",
  "Gringotts",
  "Gryzzl",
  "H&H Tool Company",
  "Hairy Shearers",
  "Halcyon Holdings Corporation",
  "Hammocks Are Us",
  "Hanso Foundation",
  "Hephaestus Mining Company",
  "Hey, Big Suspenders!",
  "Holobites",
  "Hooli",
  "Hubris Comics",
  "Hudsucker Industries",
  "I Can't Believe It's Not Brother: DNA Testing",
  "InGen",
  "Initech",
  "Integrated Integrals",
  "Ionic Symphonic Protonic Electronics",
  "Jean on Me",
  "Jebediah Kerman's Junkyard and Spacecraft Parts Co",
  "Junk & Disorderly Storage",
  "Jurassic Park",
  "Kaiba Corporation",
  "Kerbal Motion LLC",
  "Kerbin World-Firsts Record Keeping Society",
  "Kerbodyne",
  "Kerlington Model Rockets and Paper Products Inc",
  "Kiki's Delivery Service",
  "King Toots",
  "Kingdom Hospital",
  "Kiroshi Optics",
  "Krusty Burger",
  "Krusty Krab",
  "Krusty-O",
  "Kwik-E-Mart",
  "Lackluster Video",
  "Lacuna,  Inc.",
  "Lamborgotti",
  "Leftorium",
  "LexCorp",
  "Liberty Diner",
  "Little Shop of Hulas",
  "Los Pollos Hermanos",
  "Lou's Reeds Wind Instruments",
  "Low-Cal Calzone Zone",
  "MacLaren's Pub",
  "Macmillan Toys",
  "Macroware",
  "Madrigal Electromotive GmbH",
  "Magnum G.I. Colonoscopies",
  "Maisel and Roth Garment Company",
  "Manger Danger Babyproofing",
  "Mann Co.",
  "Mao-Kwikowski Mercantile",
  "Maroon Cartoons",
  "Masala Studios",
  "Masamune",
  "Massive Dynamics",
  "Matsumura Fishworks",
  "Maxo Construction Toys",
  "Mayberry Police Department",
  "McMann & Tate Advertising",
  "McNamara/Troy",
  "Meet the Patents - Patent Attorney",
  "Mega Lo mart",
  "Megadodo Publications",
  "Militech",
  "Mitch and Murray",
  "Mom's Friendly Robot Company",
  "Monarch Steller Industries",
  "Moving Parts Experts Group",
  "Mr. Plow",
  "Mrs. Cookielady",
  "Multi National United",
  "My So-Called Knife Butterknife Store",
  "Nakatomi Trading Co.",
  "NCART",
  "NicolaNaranjita",
  "North by Knockwurst Sausage Store",
  "North Central Positronics",
  "Nozz-a-la Cola",
  "Nuka-Cola",
  "O.M.B. Demolition Enterprises",
  "Oceanic Airlines",
  "Olivia Pope & Associates",
  "Ollivander's Wand Shop",
  "Omni Consumer Products",
  "Orbital Air",
  "Oscorp",
  "Overly Complex Incorporated",
  "Owed to Joy - Personal Loans",
  "Pair of Dice City - Dice Outlet",
  "Paper St. Soap Co.",
  "Passiflora",
  "Pasty Ray's Tanning Salon",
  "Pawnee City Council",
  "Pawtucket Patt",
  "Pear Nol Holiday Fruit",
  "Penny for Your Tots Daycare",
  "Periapsis Rocket Supplies Co",
  "Phil Dunphy Real Estate",
  "Pied Piper",
  "Pierce and Pierce",
  "Piez",
  "Planet Express",
  "Pokey Piercings",
  "Prescott Pharmaceuticals",
  "Prestige Worldwide",
  "Primatech Paper",
  "Pritchett Closets & Blinds",
  "Probodobodyne Inc",
  "Prodigy Corporation",
  "Protogen",
  "Quadra",
  "Quahog Community Center",
  "Quick Stop",
  "Quilty as Charged",
  "Radiator King",
  "Raviga Capital Management",
  "Red Blazer Realty",
  "Regret Me Not Tattoo",
  "Resisting A Rest Sleep Therapy",
  "Reynholm Industries",
  "Rizzo's",
  "RobCo Industries",
  "Rockomax Conglomerate",
  "Rokea Inc",
  "Ronco",
  "Roxxon",
  "Royal Charter Energy",
  "Rude A-Bake-Ening",
  "Sacred Heart Hospital",
  "Sandpiper Airlines",
  "Saul Goodman Law",
  "Savage Industries",
  "Sean's Cannery",
  "Serrano Genomics",
  "Shall We Pants?",
  "Sheinhardt Wig Company",
  "Shulman's Women's Health Associates",
  "SHWABSHWAB",
  "Silph Co.",
  "Silver Shamrock Novelties",
  "Simply the Asbestos",
  "Sirius Cybernetic",
  "Slate Rock and Gravel Company",
  "Slusho!",
  "Smoothie Operator",
  "Snake Pit Bar and Saloon",
  "Snakejuice",
  "Soylent Corporation",
  "Spacely's Space Sprockets",
  "Spacer's Choice",
  "Spooners",
  "Springfield Nuclear Plant",
  "Spunky Monkey",
  "SS Minnow Charter Tours",
  "Star Helix Security",
  "Stark Industries",
  "Sterling Cooper and Partners",
  "Stevens & Lido",
  "Stickers for Men",
  "Stop in the Name of Gloves",
  "Strickland Propane",
  "Takes All Rinds - Composting Center",
  "Takuro Auto",
  "Tamaribuchi Heavy Manufacturing Concern",
  "Tasty Freeze",
  "Tekhtronika LTD",
  "Tet Corporation",
  "That's A-Door-A-Bell Doorbells",
  "The Bannered Mare",
  "The Bluth Company",
  "The Cherry Pit",
  "The Codfather Fish & Chips",
  "The Daily Planet",
  "The DHARMA Initiative",
  "The Dragonfly Inn",
  "The El Dente Dentist",
  "The Flannel Islands",
  "The Frying Dutchman",
  "The Fudge-itive",
  "The Gaslight Caf",
  "The Hanso Foundation",
  "The Lanford Lunch Box",
  "The Lids Are All Tight: Storage Containers",
  "The Live Corp Company",
  "The Merchant of Tennis",
  "The Outlet Outlet",
  "The Peach Pit",
  "The Pie Hole",
  "The Pie Palace",
  "The Road Less Graveled Asphalt Paving",
  "The Snugly Duckling",
  "The Stuff",
  "The Thesaurus Shop - Store - Market - Boutique",
  "The Very Big Corporation of America",
  "The Zaibatsu Corporation",
  "There Yacht-A Be A Law: Maritime Lawyers",
  "Thorton",
  "Those Who Can, dle Candles",
  "Town of Woodbury",
  "Tri-Borough Plastics",
  "Trial Analysis Corporation",
  "Tru Blood",
  "Try-N-Save",
  "Tycho Manufacturying and Engineering Concern",
  "Tyrell Corp.",
  "Ultor Corporation",
  "Umbrella Corporation",
  "Union Aerospace Corporation",
  "Unnecessaries",
  "Upton-Webber",
  "Vamanos Pest Control",
  "Vandelay Industries",
  "Vault-Tec Corporation",
  "Veidt Industries",
  "Vermont Highway Patrol",
  "VersaLife Corporation",
  "Very Good Building",
  "Villefort",
  "Vimme Vivaldi Bank",
  "Virtucon",
  "Visor Advisor",
  "Vought International",
  "Walley World",
  "Warbucks Industries",
  "Ward Electric",
  "Wash n' Run",
  "Wattz Electronics",
  "Wayne Enterprises",
  "We'll Always Have Ferrets",
  "Weight For It Gym Equipment",
  "WESAYSO Corporation",
  "Weyland Industries",
  "Weyland-Yutani",
  "Whacky Khaki",
  "Whine Country Marriage Counseling",
  "White Country - Marriage Counseling",
  "Whole Lotta Shaker Furniture Going On",
  "Wonka Industries",
  "You Can't Handle the Ruth Baseball Cards",
  "You Walkin' To Me? Physical Therapy",
  "You're Missing the Poinsettia",
  "Youngstown State Football",
  "Yoyodyne Propulsion Systems",
  "Zetatech",
  "Zombieland"
];

/**
 * Predefined field values for Quick Order (QO) form tests.
 */

export const demoScripts = {
  demo30sScript: `Raw copy for a spot can be entered on the QO form or into the "Script Timer" tool. Pronunciation guides can make sure voice talent say things right the first time. This sentence is a pronunciation nightmare with out it:

The mischievous Deputy Quahog went from Tucson to Worcester to buy the acai berries from Versailles that dilate your eyes.

You'll also see a read-time estimate based on the formula of ninety words per thirty seconds at a naturally paced read. This formula can be adjusted locally if you prefer it to be more relaxed or not.

[Anything that is entered between parenthesis or brackets]
(Will not be counted towards the length estimate)`,

  demo60sScript: `Raw copy for a spot can be entered on the QO form or into the "Script Timer" tool. Pronunciation guides can make sure voice talent will say things right the first time. This sentence is a pronunciation nightmare without it:

The mischievous Deputy Quahog went from Tucson to Worcester to buy the acai berries from Versailles that dilate your eyes.

You'll also see a read-time estimate based on the formula of ninety words per thirty seconds at a naturally paced read. This formula can be adjusted locally if you prefer it to be more relaxed or not.

[Anything that is entered between parenthesis or brackets]
(Will not be counted towards the length estimate)

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Mauris efficitur, ipsum nec lacinia euismod, dui ante porta orci, eu pharetra felis turpis nec felis. Vivamus sit amet nisi ac mauris pretium eleifend. Quisque eleifend erat varius laoreet ultrices. Sed feugiat lectus non interdum feugiat. Ut in neque a sapien cursus egestas. Nulla sapien libero, blandit eget dignissim ac, pharetra nec lacus. In hac habitasse platea dictumst. Nulla sodales suscipit vulputate. Donec sagittis dui a auctor porta. Fusce maximus lectus metus, non pretium.`
};

export const demoNotes = {
  prodNotes: `This area is used to provide production staff with any instructions or additional details that they will need to know.`,

  digitalNotes: `This area is used to provide web/digital staff with any instructions or additional details like the SMS/Mobile/Twitter message they'll be broadcasting.`,

  trafficNotes: `This area is used to provide traffic or continuity staff with any instructions or additional details that they will need to know.`,

  blogNotes: `This blog window allows you to communicate with everyone involved. This is where you will enter information that you need everyone to know.`,

  creativeNotes: `This field is for inputting any and all notes that the writing or creative team may need. We can also have this area auto-populate with a block of needs or bullet points such as

SLOGAN:

CONSUMER BENEFIT:

PRIMARY/SECONDARY OFFER:

CLIENT COMMENTS/PREFERENCES:`,

  tagCopy: `This field is used to submit the simple and short tags that are added onto spots. These are usually just five or ten seconds long, read by local staff and added to existing audio.`
};